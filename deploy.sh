#!/bin/bash

# Smart Assess Backend Deployment Script
echo "Starting Smart Assess Backend deployment..."

# Check if the GitHub CLI is installed
if ! command -v gh &> /dev/null; then
    echo "Installing GitHub CLI..."
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
    apt update
    apt install gh -y
fi

# Login to GitHub CLI (will open browser or provide device code)
echo "Please authenticate with GitHub..."
gh auth login

# Clone the private repository using GitHub CLI
echo "Cloning the repository..."
gh repo clone smart-Assess/smart-assess-backend
cd smart-assess-backend

# Create .env file
echo "Setting up environment variables..."
cat > .env << EOL
# Add your environment variables below
# For example:
AWS_ACCESS_KEY_ID=AKIAXEVXYKXJWVAMLSRO
AWS_SECRET_ACCESS_KEY=QVMebvTj+xiJuj73+WU97JweewMcfhFTeuunqKOI
AWS_DEFAULT_REGION=us-east-1
S3_BUCKET_NAME=smartassessfyp
QDRANT_API_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIiwiZXhwIjoxNzQ3MzM3NzY4fQ.AEDv7pPyzgF2U1Od9NGbmcC2r5LahxLIPyb_KybZYhQ
MONGO_URI=mongodb+srv://smartassessfyp:SobazFCcD4HHDE0j@fyp.ad9fx.mongodb.net/?retryWrites=true&w=majority
QDRANT_URL=https://3c2bb745-57c0-478a-b61f-af487f8382e8.eu-central-1-0.aws.cloud.qdrant.io:6333
# AI_DETECTION_HOST="ai-detection"
EOL

# Open the .env file for editing
echo "Please edit the .env file with your environment variables..."
nano .env

# Configure firewall
echo "Configuring firewall..."
ufw allow 8000/tcp
ufw allow 5000/tcp
ufw reload

# Build and start containers
echo "Building and starting Docker containers..."
docker compose up -d --build

# Show status
echo "Checking deployment status..."
docker ps

echo ""
echo "Deployment completed!"
echo "Your API should now be accessible at:"
echo "- Main API: http://$(curl -s ifconfig.me):8000"
echo "- API Documentation: http://$(curl -s ifconfig.me):8000/docs"
echo ""
echo "To view logs: docker compose logs -f"
echo "To restart services: docker compose restart"
echo "To stop services: docker compose down"
echo ""
echo "Thank you for using Smart Assess Backend!"
