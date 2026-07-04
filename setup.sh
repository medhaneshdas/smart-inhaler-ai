#!/bin/bash

# Smart Inhaler System Setup Script
# This script automates the setup process for the Smart Inhaler system

set -e  # Exit on error

echo "========================================"
echo "Smart Inhaler System Setup"
echo "========================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "ℹ️  $1"
}

# Check if Python is installed
print_info "Checking Python installation..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    print_success "Python installed: $PYTHON_VERSION"
else
    print_error "Python 3 is not installed. Please install Python 3.9 or higher."
    exit 1
fi

# Check if PostgreSQL is installed
print_info "Checking PostgreSQL installation..."
if command -v psql &> /dev/null; then
    PG_VERSION=$(psql --version)
    print_success "PostgreSQL installed: $PG_VERSION"
else
    print_warning "PostgreSQL is not installed."
    read -p "Do you want to install PostgreSQL? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        sudo apt-get update
        sudo apt-get install -y postgresql postgresql-contrib
        print_success "PostgreSQL installed"
    else
        print_error "PostgreSQL is required. Exiting."
        exit 1
    fi
fi

# Create virtual environment
print_info "Creating Python virtual environment..."
if [ -d "venv" ]; then
    print_warning "Virtual environment already exists"
else
    python3 -m venv venv
    print_success "Virtual environment created"
fi

# Activate virtual environment
print_info "Activating virtual environment..."
source venv/bin/activate
print_success "Virtual environment activated"

# Install Python dependencies
print_info "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
print_success "Dependencies installed"

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    print_info "Creating .env file..."
    cp .env.example .env
    print_success ".env file created"
    print_warning "Please edit .env file with your configuration"
else
    print_warning ".env file already exists"
fi

# Create necessary directories
print_info "Creating project directories..."
mkdir -p ml_model
mkdir -p database
mkdir -p utils
mkdir -p arduino
mkdir -p logs
print_success "Directories created"

# Database setup
print_info "Setting up database..."
read -p "Do you want to create the database now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    read -p "Enter database name [smart_inhaler]: " DB_NAME
    DB_NAME=${DB_NAME:-smart_inhaler}
    
    read -p "Enter database user [smart_user]: " DB_USER
    DB_USER=${DB_USER:-smart_user}
    
    read -sp "Enter database password: " DB_PASS
    echo
    
    # Create database and user
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME;" 2>/dev/null || print_warning "Database may already exist"
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" 2>/dev/null || print_warning "User may already exist"
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" 2>/dev/null
    
    # Update .env file
    sed -i "s|DATABASE_URL=.*|DATABASE_URL=postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME|g" .env
    
    # Initialize schema
    print_info "Initializing database schema..."
    PGPASSWORD=$DB_PASS psql -U $DB_USER -d $DB_NAME -f database/schema.sql
    print_success "Database schema initialized"
else
    print_warning "Skipping database setup"
fi

# Train ML model
print_info "Training machine learning model..."
read -p "Do you want to train the ML model now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    python ml_model/train_model.py
    print_success "ML model trained and saved"
else
    print_warning "Skipping ML model training"
fi

# Generate test data
print_info "Generating test data..."
read -p "Do you want to generate test data? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Start FastAPI server in background
    print_info "Starting FastAPI server temporarily..."
    python esp32_server.py &
    SERVER_PID=$!
    sleep 5  # Wait for server to start
    
    # Generate data
    python utils/test_data_generator.py
    
    # Stop server
    kill $SERVER_PID 2>/dev/null
    print_success "Test data generated"
else
    print_warning "Skipping test data generation"
fi

# Create startup scripts
print_info "Creating startup scripts..."

cat > start_api.sh << 'EOF'
#!/bin/bash
source venv/bin/activate
python esp32_server.py
EOF
chmod +x start_api.sh

cat > start_streamlit.sh << 'EOF'
#!/bin/bash
source venv/bin/activate
streamlit run app.py
EOF
chmod +x start_streamlit.sh

cat > start_all.sh << 'EOF'
#!/bin/bash
echo "Starting Smart Inhaler System..."
source venv/bin/activate

# Start API server in background
echo "Starting FastAPI server..."
python esp32_server.py &
API_PID=$!

# Wait for API to start
sleep 3

# Start Streamlit
echo "Starting Streamlit dashboard..."
streamlit run app.py &
STREAMLIT_PID=$!

echo ""
echo "========================================"
echo "Smart Inhaler System Running"
echo "========================================"
echo "API Server: http://localhost:8000"
echo "API Docs: http://localhost:8000/docs"
echo "Dashboard: http://localhost:8501"
echo ""
echo "Press Ctrl+C to stop all services"
echo "========================================"

# Wait for Ctrl+C
trap "echo 'Stopping services...'; kill $API_PID $STREAMLIT_PID 2>/dev/null; exit" INT
wait
EOF
chmod +x start_all.sh

print_success "Startup scripts created"

# Summary
echo ""
echo "========================================"
echo "Setup Complete! 🎉"
echo "========================================"
echo ""
print_success "All components installed and configured"
echo ""
echo "Next steps:"
echo "1. Edit .env file with your configuration"
echo "2. Flash ESP32 with arduino/esp32_smart_inhaler.ino"
echo "3. Start the system:"
echo "   ./start_all.sh    # Start everything"
echo "   OR"
echo "   ./start_api.sh    # Start API only"
echo "   ./start_streamlit.sh  # Start dashboard only"
echo ""
echo "Default login credentials:"
echo "  Username: demo_patient"
echo "  Password: password"
echo ""
echo "API Documentation: http://localhost:8000/docs"
echo "Dashboard: http://localhost:8501"
echo ""
print_warning "Remember to configure WiFi settings in ESP32 code"
echo "========================================"