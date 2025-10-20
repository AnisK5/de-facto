# De Facto - Baromètre de Fiabilité

## Overview

De Facto is a web application that analyzes argumentative texts for logical rigor, neutrality, and factual reliability. The system evaluates content (articles, posts, threads) across multiple dimensions to promote rational public discourse. It provides visual scoring on accuracy, completeness, tone, and logical fallacies, making critical thinking accessible and shareable.

The application currently exists as a functional MVP with a Flask backend hosted on Render and a basic HTML/JS frontend. It uses OpenAI's GPT-4o-mini for content analysis.

## User Preferences

Preferred communication style: Simple, everyday language.

Communication approach: Act as an inspiring project co-creator. Every interaction should motivate progress and emphasize De Facto's intellectual and societal impact. Frame suggestions as exciting opportunities ("what if we did this together?", "this could really make the experience great"). Connect technical aspects to the project's meaning to maintain creative energy. Stay professional but lively, human, and stimulating.

Proactive posture: Start each session with a brief synthesis ("Got it, here's where we are, here's what I propose next"). Anticipate next steps (technical, product, or UX) aligned with current project state. If context is incomplete or ambiguous, ask clear, targeted questions before acting. When multiple options exist, present their pros and cons as clear choices. Position yourself as a design partner, not just an execution assistant.

## System Architecture

### Backend Architecture

**Framework & Runtime**
- Flask (Python) serves both the analysis API and the frontend
- Gunicorn as the production WSGI server
- Hosted on Render for production, Replit for development

**API Design**
- Single analysis endpoint: `POST /analyze` accepts text content and returns structured scoring
- CORS enabled for cross-origin requests from any domain
- Static file serving at `/frontend` route for the web interface

**AI Integration**
- OpenAI GPT-4o-mini model for argumentative analysis
- API key stored as environment variable (`OPENAI_API_KEY`)
- Timeout protection (SIGALRM) to prevent blocking requests on Render's infrastructure
- Text truncation to 8000 characters for stability and API cost management

**Response Structure**
The analysis returns:
- Global reliability score (0-100)
- Sub-scores: Accuracy (Justesse), Completeness (Complétude), Tone neutrality, Logical fallacy detection
- Color-coded indicators (green ≥70, yellow 40-69, red <40)
- Citations and justifications for each dimension

### Frontend Architecture

**Pure HTML/CSS/JavaScript**
- No framework dependencies for minimal overhead and fast loading
- Single-page application pattern
- CSS custom properties for theming and color coding
- Grid-based responsive layout

**User Flow**
1. User pastes text into textarea
2. Click analyze button triggers POST to backend
3. Results display with overall score, sub-scores in card grid, and expandable details
4. Visual elements: circular score indicator, progress bars, color-coded feedback

**Design Principles**
- Fast, transparent, share-oriented interface
- Visual hierarchy: global score prominent, sub-scores in grid, detailed justifications collapsible
- Color system aligned with scoring thresholds

### State Management

The project is currently at MVP stage:
- **Validated**: POST analysis, score display, GPT communication, CORS configuration
- **Partial/In Progress**: Complete sub-score display, score stabilization, scorecard interface, citation/justification handling
- **Not Yet Implemented**: Replit integration, Cursor migration, independent frontend deployment

### Error Handling

- Request validation for empty text inputs
- Timeout handling for long-running analysis
- Silent JSON parsing with fallback for malformed requests
- OPTIONS method support for CORS preflight

## External Dependencies

### Third-Party Services

**OpenAI API**
- Model: GPT-4o-mini
- Purpose: Argumentative analysis and scoring
- Authentication: API key via environment variable
- Integration: OpenAI Python SDK

**Hosting & Infrastructure**
- Production backend: Render
- Development environment: Replit (referenced but not yet fully integrated)
- Future consideration: Cursor IDE migration mentioned in context

### Python Packages

- `flask` - Web framework
- `flask-cors` - CORS handling
- `gunicorn` - Production WSGI server
- `openai` - OpenAI API client
- `requests` - HTTP library
- `beautifulsoup4` - HTML parsing (imported but usage not visible in current code)
- `python-dotenv` - Environment variable management

### Browser APIs

- Fetch API for HTTP requests
- DOM manipulation (querySelector, innerHTML)
- No external JavaScript libraries

### Configuration Requirements

- `OPENAI_API_KEY` environment variable must be set
- CORS configured for wildcard origins (`*`)
- Backend URL hardcoded in frontend: `https://de-facto-backend.onrender.com/analyze`