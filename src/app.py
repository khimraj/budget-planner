"""
Flask web application for Budget Planner with CSV upload and LiveKit voice agent integration.
"""

from flask import Flask, request, jsonify, render_template, session, send_from_directory
from flask_cors import CORS
import os
import logging
from werkzeug.utils import secure_filename
import pandas as pd
from livekit import api
from datetime import timedelta
from dotenv import load_dotenv
import secrets
import subprocess
import atexit
import signal
import sys

# Load environment variables from .env.local
load_dotenv(".env.local")

from csv_parser import parse_csv_with_llm, save_transactions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variable to hold the agent process
agent_process = None

def start_agent():
    """Start the LiveKit agent as a subprocess."""
    global agent_process
    
    if agent_process is not None:
        logger.warning("Agent process already running")
        return
    
    try:
        logger.info("Starting LiveKit agent...")
        # Get the project root directory (parent of src/)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # Start the agent using uv run
        agent_process = subprocess.Popen(
            ["uv", "run", "python", "src/agent.py", "dev"],
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered
        )
        logger.info(f"LiveKit agent started with PID: {agent_process.pid}")
    except Exception as e:
        logger.error(f"Failed to start agent: {e}")
        agent_process = None

def stop_agent():
    """Stop the LiveKit agent subprocess."""
    global agent_process
    
    if agent_process is None:
        return
    
    try:
        logger.info(f"Stopping LiveKit agent (PID: {agent_process.pid})...")
        agent_process.terminate()
        
        # Wait for graceful shutdown
        try:
            agent_process.wait(timeout=5)
            logger.info("Agent stopped gracefully")
        except subprocess.TimeoutExpired:
            logger.warning("Agent didn't stop gracefully, forcing shutdown...")
            agent_process.kill()
            agent_process.wait()
            logger.info("Agent forcefully stopped")
    except Exception as e:
        logger.error(f"Error stopping agent: {e}")
    finally:
        agent_process = None

def cleanup_on_exit():
    """Cleanup function to stop agent when Flask exits."""
    stop_agent()

# Register cleanup handlers
atexit.register(cleanup_on_exit)
signal.signal(signal.SIGTERM, lambda signum, frame: cleanup_on_exit())
signal.signal(signal.SIGINT, lambda signum, frame: (cleanup_on_exit(), sys.exit(0)))

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))
app.config['UPLOAD_FOLDER'] = 'data/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)

# Enable CORS
CORS(app)

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Allowed file extensions
ALLOWED_EXTENSIONS = {'csv', 'txt'}


def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/')
def index():
    """Main upload page."""
    return render_template('index.html')


@app.route('/transactions')
def transactions_page():
    """Transaction display page."""
    return render_template('transactions.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle CSV file upload and parsing."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Please upload a CSV file.'}), 400
        
        # Read file content
        file_content = file.read().decode('utf-8')
        
        # Parse CSV using LLM
        logger.info("Parsing CSV with LLM...")
        df_parsed = parse_csv_with_llm(file_content)
        
        # Save to session-specific file
        session_id = session.get('session_id')
        if not session_id:
            session_id = secrets.token_hex(16)
            session['session_id'] = session_id
            session.permanent = True
        
        # Save to both session-specific and global file
        session_csv_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{session_id}.csv")
        save_transactions(df_parsed, session_csv_path)
        
        # Also save to global file for voice agent access (temporary solution)
        save_transactions(df_parsed, "transactions.csv")
        
        # Store in session
        session['transactions'] = df_parsed.to_dict('records')
        session['csv_path'] = session_csv_path
        
        logger.info(f"Successfully parsed {len(df_parsed)} transactions")
        
        return jsonify({
            'success': True,
            'message': f'Successfully parsed {len(df_parsed)} transactions',
            'count': len(df_parsed),
            'transactions': df_parsed.to_dict('records')
        })
        
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    """Get parsed transactions from session."""
    transactions = session.get('transactions', [])
    
    if not transactions:
        return jsonify({'transactions': [], 'message': 'No transactions found. Please upload a CSV file.'}), 200
    
    return jsonify({'transactions': transactions})


@app.route('/api/livekit-token', methods=['POST'])
def get_livekit_token():
    """Generate LiveKit access token for voice agent connection."""
    try:
        # Get room name from request or use default
        data = request.get_json(silent=True) or {}
        room_name = data.get('room', 'budget-planner-room')
        participant_name = data.get('participant', f'user-{secrets.token_hex(4)}')
        
        # Get LiveKit credentials from environment
        livekit_url = os.getenv('LIVEKIT_URL')
        livekit_api_key = os.getenv('LIVEKIT_API_KEY')
        livekit_api_secret = os.getenv('LIVEKIT_API_SECRET')
        
        if not all([livekit_url, livekit_api_key, livekit_api_secret]):
            return jsonify({
                'error': 'LiveKit credentials not configured. Please set LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET in environment.'
            }), 500
        
        # Create access token
        token = api.AccessToken(livekit_api_key, livekit_api_secret)
        token.with_identity(participant_name)
        token.with_name(participant_name)
        token.with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
        ))
        
        jwt_token = token.to_jwt()
        
        return jsonify({
            'token': jwt_token,
            'url': livekit_url,
            'room': room_name,
            'participant': participant_name
        })
        
    except Exception as e:
        logger.error(f"Error generating LiveKit token: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/clear-session', methods=['POST'])
def clear_session():
    """Clear session data."""
    session.clear()
    return jsonify({'success': True, 'message': 'Session cleared'})


if __name__ == '__main__':
    # Start the LiveKit agent first
    start_agent()
    
    try:
        # Run Flask on port 8000
        app.run(host='0.0.0.0', port=8000, debug=True, use_reloader=False)
    finally:
        # Ensure agent is stopped when Flask exits
        stop_agent()
