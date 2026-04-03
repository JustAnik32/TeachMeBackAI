# TeachMeBack — AI-Powered Learning Platform

**Learn by teaching. The Feynman Technique, scaled by AI.**

TeachMeBack is an AI learning platform where students teach concepts to an AI student. The AI asks questions, identifies knowledge gaps, and creates comprehension heatmaps for teachers.

## 🎯 Problem

- 67% of teachers can't identify learning gaps until the test
- Current tools show **completion**, not **comprehension**
- Students fall through cracks, teachers are reactive not proactive

## 💡 Solution

1. Teacher assigns topic: "Explain Photosynthesis"
2. Student **teaches AI** (forces articulation, not memorization)
3. AI analyzes gaps → generates comprehension heatmap
4. Teacher sees: Who struggles + exactly what concept

## ✨ Features

- **AI Socratic Method**: AI plays curious student, asks probing questions
- **Plagiarism Detection**: Prevents copying AI responses
- **Tab Switch Monitoring**: Ensures focus during teaching
- **Teacher Dashboard**: Class comprehension heatmap
- **Knowledge Gap Mapping**: Visual roadmap of understanding

## 🚀 Quick Start

### Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend
Open `frontend/teachmeback.html` in browser

## 🔧 Tech Stack

- **Backend**: FastAPI, Python, OpenRouter AI
- **Frontend**: HTML, JavaScript, CSS
- **AI**: GPT-4o-mini via OpenRouter

## 📝 Environment Variables

Create `backend/.env`:
```
OPENROUTER_API_KEY=your_key_here
```

## 🏆 Competition

Built for **INNOSpark Pitch Competition** — $20,000 global virtual pitch competition for high school entrepreneurs.

**Pitch Focus**: Teacher Dashboard (B2B K-12 education market)

## 📄 License

Hackathon demo — built with ❤️ for INNOSpark 2026
