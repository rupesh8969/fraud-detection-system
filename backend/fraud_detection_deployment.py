from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import torch
import torch.nn as nn
import logging
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load the model
MODEL_PATH = os.path.join(os.path.dirname(__file__), "fraud_detection_model.pth")
# Verify model file exists
if not os.path.exists(MODEL_PATH):
    logger.error(f"Model file not found at: {MODEL_PATH}")
    logger.info("Please ensure the model file is placed in the same directory as this script")

class FraudDetectionModel(nn.Module):
    def __init__(self, input_size):
        super(FraudDetectionModel, self).__init__()
        self.fc1 = nn.Linear(input_size, 128)
        self.fc2 = nn.Linear(128, 64)
        self.fc3 = nn.Linear(64, 1)
        self.relu = nn.ReLU()
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        x = self.relu(self.fc1(x))
        x = self.relu(self.fc2(x))
        x = self.sigmoid(self.fc3(x))
        return x

class FraudDetector:
    def __init__(self):
        self.threshold = 0.5
        self.high_risk_patterns = {
            'multiple_quick': lambda x: max(x[0:3]) > 0.8,
            'unusual_amount': lambda x: abs(x[4] - x[5]) > 0.5,
            'international': lambda x: x[8] > 0.7 and x[9] > 0.7,
            'night_time': lambda x: x[12] > 0.6 and x[13] > 0.6
        }

    def analyze_patterns(self, features):
        risks = []
        for pattern_name, check_fn in self.high_risk_patterns.items():
            if check_fn(features):
                risks.append(pattern_name)
        return risks

class FraudScorer:
    def __init__(self):
        self.risk_weights = {
            'transaction_pattern': 0.3,    # Features 0-2
            'location_match': 0.2,         # Features 3-5
            'amount_pattern': 0.15,        # Features 6-8
            'temporal_pattern': 0.15,      # Features 9-11
            'user_behavior': 0.2          # Features 12-14
        }
        
    def calculate_score(self, features):
        """Calculate fraud score (0-100, higher means more risky)"""
        risk_factors = {
            'transaction_pattern': max(features[0:3]),
            'location_match': abs(features[3] - features[5]),
            'amount_pattern': max(features[6:9]),
            'temporal_pattern': sum(features[9:12]) / 3,
            'user_behavior': max(features[12:15])
        }
        
        logger.info(f"Risk factors: {risk_factors}")  # Add logging for debugging

        score = sum(risk_factors[k] * self.risk_weights[k] for k in self.risk_weights) * 100
        return min(100, max(0, score))

    def get_risk_breakdown(self, features):
        """Get detailed risk analysis for each factor"""
        return {
            'transaction_pattern': {
                'score': max(features[0:3]) * 100,
                'description': 'Multiple quick purchases or unusual patterns'
            },
            'location_match': {
                'score': abs(features[3] - features[5]) * 100,
                'description': 'Distance between IP and billing location'
            },
            'amount_pattern': {
                'score': max(features[6:9]) * 100,
                'description': 'Unusual transaction amount patterns'
            },
            'temporal_pattern': {
                'score': (sum(features[9:12]) / 3) * 100,
                'description': 'Time-based transaction patterns'
            },
            'user_behavior': {
                'score': max(features[12:15]) * 100,
                'description': 'User behavior and history'
            }
        }

# Create FastAPI instance
app = FastAPI()
fraud_detector = FraudDetector()
fraud_scorer = FraudScorer()

# Add CORS middleware to allow requests from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define input data schema
class FraudInput(BaseModel):
    features: list[float]

# Load the trained model
try:
    input_size = 15  # Changed back to 15 to match the saved model
    model = FraudDetectionModel(input_size)
    if os.path.exists(MODEL_PATH):
        try:
            state_dict = torch.load(MODEL_PATH, map_location=torch.device('cpu'))
            logger.info(f"Model state dict keys: {state_dict.keys()}")
            model.load_state_dict(state_dict)
            model.eval()
            logger.info("Model loaded successfully!")
        except Exception as e:
            logger.error(f"Error loading model state dict: {str(e)}")
            model = None
    else:
        logger.error(f"Model file not found at: {MODEL_PATH}")
        logger.info("Please place the fraud_detection_model.pth file in the backend directory")
        model = None
except Exception as e:
    logger.error(f"Error initializing model: {str(e)}")
    model = None

# Prediction endpoint
@app.post("/predict/")
async def predict(data: FraudInput):
    logger.info("Received prediction request")
    
    if not model:
        logger.error("Model not loaded")
        raise HTTPException(
            status_code=500, 
            detail="Model not loaded. Please check server logs."
        )
    
    try:
        features = data.features
        logger.info(f"Received features: {features}")

        if len(features) != 15:
            logger.error(f"Invalid feature count: {len(features)}")
            raise HTTPException(
                status_code=400, 
                detail=f"Input must contain exactly 15 features, got {len(features)}"
            )

        # Convert input to tensor
        input_tensor = torch.tensor([features], dtype=torch.float32)
        logger.info(f"Input tensor shape: {input_tensor.shape}")

        # Make prediction
        with torch.no_grad():
            probability = model(input_tensor).item()
            logger.info(f"Model probability: {probability}")

        # Calculate fraud score and risk breakdown
        fraud_score = fraud_scorer.calculate_score(features)
        risk_breakdown = fraud_scorer.get_risk_breakdown(features)
        risk_patterns = fraud_detector.analyze_patterns(features)

        logger.info(f"Fraud score: {fraud_score}")
        logger.info(f"Risk patterns detected: {risk_patterns}")

        # Determine overall risk level
        risk_level = "high" if fraud_score > 70 else "medium" if fraud_score > 30 else "low"

        response_data = {
            "fraud": fraud_score > 70,
            "fraud_score": float(fraud_score),
            "probability": float(probability),
            "risk_patterns": risk_patterns,
            "risk_breakdown": risk_breakdown,
            "risk_level": risk_level,
            "recommendation": "decline" if fraud_score > 70 else "review" if fraud_score > 30 else "approve"
        }
        
        logger.info(f"Sending response: {response_data}")
        return response_data

    except Exception as e:
        logger.exception("Prediction error occurred")
        raise HTTPException(
            status_code=500,
            detail=f"Error during prediction: {str(e)}"
        )

# Health check endpoint
@app.get("/")
def read_root():
    return {"message": "Fraud Detection API is running!"}
