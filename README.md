# Voice-Powered Budget Planner

A specialized voice AI assistant built with [LiveKit Agents](https://github.com/livekit/agents), [LangGraph](https://github.com/langchain-ai/langgraph), and [Flask](https://flask.palletsprojects.com/). This application allows users to upload financial transaction CSVs and interact with a voice agent to analyze spending patterns and plan budgets.

## Features

- **CSV Transaction Upload**: Web interface to upload and parse bank/credit card statements.
- **LLM-Powered Parsing**: Automatically cleans and categorizes transaction data using LLMs.
- **Voice Intelligence**: Natural voice interaction powered by LiveKit, OpenAI, Cartesia, and Deepgram.
- **LangGraph Integration**: Complex reasoning and data analysis using a structured graph-based workflow.
- **Python-Based Analysis**: The agent executes real Python/Pandas code to provide accurate financial insights.
- **Docker Ready**: Fully containerized for easy deployment.

## Architecture

The project consists of two main components running in parallel:

1.  **Flask Web Server (`src/app.py`)**:
    - Serves the frontend for file uploads.
    - Handles CSV parsing and data persistence.
    - Manages the LiveKit voice agent as a background process.
    - Provides tokens for frontend client connections.

2.  **LiveKit Voice Agent (`src/agent.py`)**:
    - Connects to LiveKit Cloud for real-time audio streaming.
    - Uses a LangGraph-based brain (`src/graph.py`) for decision making.
    - Accesses the uploaded CSV data to answer specific user queries.

## Setup Instructions

### Prerequisites

- [uv](https://github.com/astral-sh/uv) (recommended) or Python 3.10+
- [LiveKit Cloud](https://cloud.livekit.io/) account and credentials
- [OpenAI API Key](https://platform.openai.com/)

### Environment Variables

Copy `.env.example` to `.env` (or `.env.local`) and fill in the following:

```env
# LiveKit Credentials
LIVEKIT_URL=wss://...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...

# OpenAI API Key (for LangGraph/LLM)
OPENAI_API_KEY=sk-...
```

### Installation

```bash
# Sync dependencies
uv sync

# Download required models (VAD, Turn Detector)
uv run python src/agent.py download-files
```

## Running the Application

To start the integrated application (Flask + Voice Agent), run:

```bash
uv run python src/app.py
```

The web interface will be available at `http://localhost:8000`.

### Development Mode

If you wish to run the agent separately in your terminal for testing:

```bash
uv run python src/agent.py console
```

## Usage Guide

1.  **Upload Data**: Open the web interface and upload your transaction history (CSV or TXT).
2.  **Connect Voice**: Once uploaded, navigate to the transaction view or use the voice interface to connect.
3.  **Analyze**: Ask the agent questions about your spending.

### Example Queries

- "How much did I spend on Food last month?"
- "What are my top 3 expense categories?"
- "Help me plan a budget for next month based on my history."
- "What was my total spending in January?"

> [!IMPORTANT]
> The agent is programmed to ignore income (positive amounts) and focus solely on expense analysis (negative amounts) to provide accurate budgeting advice.

## Deployment

The project includes a `Dockerfile` optimized for production.

```bash
docker build -t budget-planner .
docker run -p 8000:8000 --env-file .env budget-planner
```

## License

MIT
