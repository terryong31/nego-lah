# Nego-lah

**Nego-lah** is a modern, second-hand online store application that features real-time AI-assisted negotiation, a sleek user interface with dark/light mode, and a comprehensive admin dashboard.

## Features

### For Users
- **Browse Items**: View a curated list of second-hand items with a beautiful, responsive UI.
- **Real-time Negotiation Chat**: Chat with the system (AI or Admin) to negotiate prices on items.
  - *Smart Typography*: Messages stream in real-time.
  - *Typing Indicators*: See when the other party is typing.
- **Theme Support**: Toggle between Dark and Light modes with a premium "wipe" transition effect.
- **Secure Authentication**: User login and sign-up powered by Supabase.

### For Admins
- **Admin Dashboard**: A centralized hub to manage the platform.
- **Item Management**: Add, edit, or remove items for sale.
- **User Management**: View and manage user accounts.
- **Order Management**: Track and update order statuses.
- **Live Chat Support**: Intercept user chats and reply in real-time.

## Technology Stack

**Frontend**
- **React 19** (Built with **Vite**)
- **TypeScript**
- **Tailwind CSS 4** (Styling)
- **Supabase Client** (Auth & Realtime)
- **React Router 7** (Navigation)

**Backend**
- **Python 3**
- **FastAPI** (High-performance API framework)
- **Supabase** (Database & Auth)
- **LangChain & Google GenAI** (AI capabilities)
- **Stripe** (Payment processing)
- **FAISS** (Vector Database for AI memory)
- **Redis** (Caching)

## Getting Started

Follow these instructions to set up the project on your local machine.

### Prerequisites
- **Node.js** (v18 or higher) installed.
- **Python 3.10+** installed.
- A **Supabase** project account.
- **Git** installed.

### 1. clone the Repository
```bash
git clone https://github.com/terryong31/nego-lah.git
cd nego-lah
```

### 2. Backend Setup
Navigate to the backend folder and set up the Python environment.

```bash
cd backend

# Create a virtual environment (macOS/Linux)
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

**Configuration (.env)**
Create a `.env` file in the root directory (or ensure it exists) with the following keys:
```env
# Supabase credentials (get these from your Supabase project settings)
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key

# Google Gemini API Key (for AI features)
GOOGLE_API_KEY=your_google_api_key

# Stripe (if using payments)
STRIPE_SECRET_KEY=your_stripe_secret_key
```

### 3. Frontend Setup
Open a new terminal window, navigate to the frontend folder, and install dependencies.

```bash
cd frontend

# Install Node modules
npm install
```

**Configuration**
Ensure the frontend knows where the backend and Supabase are. You might need a `.env` in the `frontend` directory too:
```env
VITE_API_URL=http://localhost:8000
VITE_SUPABASE_URL=your_supabase_url
VITE_SUPABASE_ANON_KEY=your_supabase_anon_key
```

## Running the Application

 You will need two terminal windows running simultaneously.

**Terminal 1: Backend**
```bash
# Make sure you are in the 'backend' folder and venv is activated
cd backend
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
*The backend API will start at `http://localhost:8000`.*

**Terminal 2: Frontend**
```bash
# Make sure you are in the 'frontend' folder
cd frontend
npm run dev -- --host
```
*The frontend will start at `http://localhost:5173` (or similar).*

## Admin Access
To access the Admin panel, navigate to `/admin` (e.g., `http://localhost:5173/admin`).
*Use the configured admin credentials to log in.*

---
*Created by [Terry Ong](https://github.com/terryong31) - Copyright \u00A9 2026*
