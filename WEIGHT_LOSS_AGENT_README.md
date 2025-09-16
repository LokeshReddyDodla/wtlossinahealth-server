# Weight Loss Agent Feature

## Overview

The Weight Loss Agent is a comprehensive AI-powered feature designed to help patients achieve sustainable weight loss through personalized monitoring, analysis, and guidance. It integrates daily meal and fitness data with inbody composition reports to provide actionable health insights.

## Key Features

### 🔒 Doctor-Only Patient Onboarding
- Only healthcare providers with "doctor" role can enroll patients
- Secure authorization ensures proper medical oversight
- Program goals and targets are set by medical professionals

### 📊 Daily Data Integration
- **Meal Reports**: Comprehensive nutritional analysis from daily meals
- **Fitness Reports**: Activity tracking, steps, calories burned, exercise patterns
- **Vital Signs**: Integration with existing patient vitals (weight, blood pressure, etc.)

### 🖼️ Inbody Report Processing
- **Image Upload**: Secure upload of inbody composition report images
- **AI-Powered OCR**: Advanced optical character recognition to extract measurements
- **Automated Processing**: Real-time extraction of body composition metrics

### 🤖 AI Health Analysis
- **Abnormality Detection**: Identifies measurements outside normal ranges
- **Personalized Insights**: AI-generated analysis based on patient profile
- **Medical Recommendations**: Evidence-based suggestions for improvement
- **Risk Assessment**: Flags concerning trends requiring medical attention

## Architecture

### Database Models

#### WeightLossAgentEnrollment
```python
- enrollment_id: UUID (Primary Key)
- patient_id: UUID (Foreign Key to patients)
- enrolled_by_care_provider_id: UUID (Doctor who enrolled patient)
- enrollment_date: DateTime
- is_active: Boolean
- program_goals: Text (JSON)
- target_weight_kg: Float
- target_bmi: Float
```

#### InbodyReport
```python
- report_id: UUID (Primary Key)
- enrollment_id: UUID (Foreign Key)
- image_url: Text (S3 URL of uploaded image)
- report_date: DateTime
- extracted_at: DateTime
- extraction_confidence: Float
- processed: Boolean
```

#### InbodyMeasurement
```python
- measurement_id: UUID (Primary Key)
- report_id: UUID (Foreign Key)
- measurement_type: String (weight, bmi, body_fat, etc.)
- value: Float
- unit: String (kg, %, cm, etc.)
- normal_min/max: Float (Reference ranges)
- confidence_score: Float
```

#### HealthIndicator
```python
- indicator_id: UUID (Primary Key)
- report_id: UUID (Foreign Key)
- indicator_name: String
- indicator_type: String (warning, critical, normal)
- value: Float
- is_abnormal: Boolean
- abnormality_level: String (low, high, critical)
- analysis_explanation: Text (AI-generated)
- recommendations: Text (AI-generated)
```

### Services

#### WeightLossAgentService
- Patient enrollment management
- Inbody report processing
- Daily data aggregation
- Progress analysis

#### InbodyImageProcessingService
- Image preprocessing and enhancement
- OCR text extraction
- Measurement pattern recognition
- Confidence scoring

#### HealthIndicatorAnalysisService
- AI-powered health analysis
- Normal range validation
- Abnormality detection
- Personalized recommendations

## API Endpoints

### Patient Enrollment
```
POST /weight-loss-agent/enroll
- Enroll patient in weight loss program (Doctor only)
- Body: WeightLossEnrollmentCreate
```

### Enrollment Management
```
PUT /weight-loss-agent/enrollment/{enrollment_id}
- Update enrollment details

GET /weight-loss-agent/patient/{patient_id}/enrollment
- Get patient's enrollment status
```

### Inbody Report Management
```
POST /weight-loss-agent/enrollment/{enrollment_id}/inbody-report
- Upload inbody report image

POST /weight-loss-agent/enrollment/{enrollment_id}/inbody-report/{report_id}/process
- Process uploaded inbody report with AI

GET /weight-loss-agent/enrollment/{enrollment_id}/inbody-reports
- Get all inbody reports for enrollment

GET /weight-loss-agent/enrollment/{enrollment_id}/inbody-report/{report_id}/health-indicators
- Get health indicators for specific report
```

### Progress Analysis
```
GET /weight-loss-agent/enrollment/{enrollment_id}/progress
- Get comprehensive progress report

POST /weight-loss-agent/enrollment/{enrollment_id}/analyze
- Generate AI-powered weight loss analysis
```

## Supported Inbody Measurements

### Core Measurements
- **Weight**: Body weight in kilograms
- **BMI**: Body Mass Index
- **Body Fat %**: Percentage of body fat
- **Muscle Mass**: Skeletal muscle mass in kg
- **Body Water %**: Total body water percentage
- **Bone Mineral**: Bone mineral content in kg

### Advanced Metrics
- **Visceral Fat**: Visceral fat level
- **BMR**: Basal Metabolic Rate in kcal
- **Waist-Hip Ratio**: WHR for cardiovascular risk
- **Body Fat Mass**: Total body fat mass in kg
- **Lean Body Mass**: Fat-free mass in kg

## AI Analysis Features

### Health Risk Assessment
- Identifies abnormal measurements
- Categorizes severity (warning, critical)
- Provides medical context and explanations

### Personalized Recommendations
- Dietary suggestions based on meal patterns
- Exercise recommendations aligned with fitness data
- Lifestyle modifications for sustainable change

### Progress Tracking
- Weight loss velocity analysis
- Metabolic health trend monitoring
- Goal achievement assessment

## Normal Ranges Reference

### BMI Categories (WHO Standards)
- **Underweight**: < 18.5
- **Normal**: 18.5 - 24.9
- **Overweight**: 25.0 - 29.9
- **Obese**: ≥ 30.0

### Body Fat Percentage (ACSM Guidelines)
- **Male**: 10-20% (ages 18-40), 11-22% (ages 40-60)
- **Female**: 18-28% (ages 18-40), 20-32% (ages 40-60)

### Other Reference Ranges
- **Visceral Fat**: 1-12 (healthy range)
- **Body Water**: 50-65% (male), 45-60% (female)
- **Waist-Hip Ratio**: < 0.95 (male), < 0.85 (female)

## Usage Workflow

### 1. Patient Enrollment (Doctor Only)
```bash
POST /weight-loss-agent/enroll
{
  "patient_id": "uuid",
  "program_goals": "Achieve sustainable weight loss of 10kg over 6 months",
  "target_weight_kg": 70.0,
  "target_bmi": 22.5
}
```

### 2. Upload Inbody Report
```bash
POST /weight-loss-agent/enrollment/{enrollment_id}/inbody-report
{
  "image_url": "s3://bucket/inbody-report.jpg",
  "report_date": "2024-01-15T10:00:00Z"
}
```

### 3. Process Report with AI
```bash
POST /weight-loss-agent/enrollment/{enrollment_id}/inbody-report/{report_id}/process
```

### 4. Get Analysis Results
```bash
GET /weight-loss-agent/enrollment/{enrollment_id}/inbody-report/{report_id}/health-indicators
```

### 5. Comprehensive Progress Report
```bash
GET /weight-loss-agent/enrollment/{enrollment_id}/progress?start_date=2024-01-01&end_date=2024-01-31
```

## Security & Authorization

### Role-Based Access Control
- **Doctors**: Can enroll patients and view all health data
- **Care Providers**: Limited access to assigned patients
- **Patients**: Can only view their own data
- **Admins**: Full system access

### Data Privacy
- All health data encrypted at rest and in transit
- HIPAA-compliant data handling
- Patient consent required for data processing
- Audit logs for all data access

## Integration Points

### Existing Systems
- **Meal Analysis Service**: Nutritional data integration
- **Fitness Tracking**: Activity and exercise data
- **Vital Signs**: Medical measurements integration
- **AI Conversation Service**: Enhanced analysis capabilities

### External Services
- **S3**: Secure image storage
- **OCR Service**: Text extraction from images
- **AI/ML Models**: Health analysis and recommendations

## Error Handling

### Common Error Scenarios
- **Invalid Image**: Unclear or corrupted inbody report
- **OCR Failure**: Unable to extract text from image
- **Authorization Error**: Non-doctor attempting enrollment
- **Data Validation**: Invalid measurement values

### Error Response Format
```json
{
  "success": false,
  "message": "Detailed error description",
  "status_code": 400,
  "error_code": "SPECIFIC_ERROR_TYPE"
}
```

## Monitoring & Analytics

### System Metrics
- Processing success rates
- Average response times
- Error rates by component
- User engagement metrics

### Health Analytics
- Patient progress tracking
- Outcome measurement
- Intervention effectiveness
- Population health trends

## Future Enhancements

### Planned Features
- **Mobile App Integration**: Direct inbody scanning
- **Wearable Device Sync**: Real-time health monitoring
- **Genetic Analysis**: Personalized recommendations based on genetics
- **Predictive Modeling**: Weight loss trajectory prediction
- **Group Programs**: Community-based weight loss challenges

### Technical Improvements
- **Advanced AI Models**: More sophisticated health analysis
- **Multi-language Support**: OCR for different languages
- **Real-time Processing**: Instant analysis results
- **Integration APIs**: Third-party health device connectivity

## Development Setup

### Prerequisites
```bash
# Install OCR dependencies
pip install pytesseract opencv-python pillow

# Install Tesseract OCR engine
# macOS: brew install tesseract
# Ubuntu: apt-get install tesseract-ocr
```

### Environment Variables
```bash
# Add to your .env file
WEIGHT_LOSS_AGENT_ENABLED=true
INBODY_PROCESSING_TIMEOUT=300
OCR_CONFIDENCE_THRESHOLD=0.7
```

### Database Migration
```bash
# Run database migrations
alembic upgrade head

# Initialize normal ranges data
python -c "from lib.initializers.weight_loss_agent_setup import initialize_weight_loss_agent_data; asyncio.run(initialize_weight_loss_agent_data(postgres_store))"
```

## Testing

### Unit Tests
```bash
# Run weight loss agent tests
pytest tests/test_weight_loss_agent/

# Run image processing tests
pytest tests/test_inbody_processing/
```

### Integration Tests
```bash
# Test full enrollment workflow
pytest tests/integration/test_weight_loss_workflow.py

# Test AI analysis pipeline
pytest tests/integration/test_ai_analysis.py
```

## Support & Documentation

### API Documentation
- Interactive API docs available at `/docs`
- Weight Loss Agent endpoints under "Weight Loss Agent" tag
- Comprehensive request/response examples

### Troubleshooting
- Check logs in `/logs/weight_loss_agent.log`
- Monitor processing status via health endpoints
- Contact development team for technical issues

---

## Contact Information

For technical support or feature requests:
- **Development Team**: dev@aihealth.com
- **Medical Oversight**: medical@aihealth.com
- **Documentation**: docs.aihealth.com/weight-loss-agent
