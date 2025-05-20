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

# Install Nginx and OpenSSL
echo "Installing Nginx and OpenSSL..."
apt update
apt install -y nginx openssl

# Create a simple self-signed certificate
echo "Creating self-signed SSL certificate..."
SERVER_IP=$(curl -s ifconfig.me)

# Create directory for certificates
mkdir -p /etc/nginx/ssl

# Generate a self-signed certificate
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/nginx.key \
  -out /etc/nginx/ssl/nginx.crt \
  -subj "/CN=${SERVER_IP}" \
  -addext "subjectAltName = IP:${SERVER_IP}"

# Create Nginx configuration file
echo "Setting up Nginx configuration..."
cat > /etc/nginx/sites-available/smart-assess << EOL
server {
    listen 443 ssl;
    
    ssl_certificate /etc/nginx/ssl/nginx.crt;
    ssl_certificate_key /etc/nginx/ssl/nginx.key;
    
    # SSL settings
    ssl_protocols TLSv1.2 TLSv1.3;
    
    # CORS headers
    add_header 'Access-Control-Allow-Origin' '*';
    add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS';
    add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization';
    
    location / {
        # Handle OPTIONS method for CORS preflight requests
        if (\$request_method = 'OPTIONS') {
            add_header 'Access-Control-Allow-Origin' '*';
            add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS';
            add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization';
            add_header 'Access-Control-Max-Age' 1728000;
            add_header 'Content-Type' 'text/plain charset=UTF-8';
            add_header 'Content-Length' 0;
            return 204;
        }
        
        proxy_pass http://localhost:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}

server {
    listen 80;
    return 301 https://\$host\$request_uri;
}
EOL

# Enable the Nginx site
ln -s /etc/nginx/sites-available/smart-assess /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default  # Remove default site

# Test Nginx configuration
nginx -t

# If configuration test is successful, restart Nginx
if [ $? -eq 0 ]; then
    systemctl restart nginx
    echo "Nginx configured successfully with SSL."
else
    echo "Nginx configuration failed. Check the error message above."
    exit 1
fi

# Configure firewall
echo "Configuring firewall..."
ufw allow 80/tcp
ufw allow 443/tcp
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
echo "- Main API: https://${SERVER_IP}"
echo "- API Documentation: https://${SERVER_IP}/docs"
echo ""
echo "NOTE: Since this is using a self-signed certificate, browsers will show a security warning."
echo "You'll need to accept the certificate warning in your browser before using the API."
echo ""
echo "To view logs: docker compose logs -f"
echo "To restart services: docker compose restart"
echo "To stop services: docker compose down"
echo ""
echo "Thank you for using Smart Assess Backend!"