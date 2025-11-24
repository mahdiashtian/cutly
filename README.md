# Cutly - Telegram File Storage Bot

A modern, scalable Telegram bot for file storage and sharing built with Telethon and Tortoise ORM.

## 🏗️ Project Structure

```
cutly/
├── app/                    # Application layer
│   ├── __init__.py
│   ├── bot.py             # Bot lifecycle management
│   ├── config.py          # Configuration management
│   └── handlers/          # Event handlers (future)
│       └── __init__.py
├── core/                  # Core functionality
│   ├── __init__.py
│   ├── database.py        # Database configuration
│   ├── models.py          # ORM models
│   └── state.py           # State machine
├── services/              # Business logic layer
│   ├── __init__.py
│   ├── backup.py          # Backup services
│   ├── channel.py         # Channel management
│   ├── file.py            # File management
│   └── user.py            # User management
├── utils/                 # Utility modules
│   ├── __init__.py
│   ├── filters.py         # Telethon filters
│   ├── helpers.py         # Helper functions
│   ├── keyboard.py        # Keyboard layouts
│   └── text.py            # Text constants
├── main.py                # Application entry point
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

## ✨ Features

- 📤 **File Upload & Storage**: Upload files up to 2GB
- 🔗 **Share Links**: Generate unique sharing links
- 🔐 **Password Protection**: Protect files with passwords
- 📝 **Custom Captions**: Add custom captions to files
- 📊 **Download Tracking**: Track file download counts
- 👥 **Admin Panel**: Comprehensive admin management
- 📢 **Broadcast Messages**: Send messages to all users
- 🎯 **Forced Join**: Require channel membership
- 🔄 **Auto Cleanup**: Automatic message cleanup after 30s
- ⚡ **Redis Cache**: High-performance caching for 1000+ concurrent users

## 🚀 Installation

### Prerequisites

- Python 3.8+
- PostgreSQL (optional, SQLite by default)
- Redis (recommended for production, optional)

### Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/cutly.git
cd cutly
```

2. Create virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Install and start Redis (optional but recommended):
```bash
# Linux/Mac
sudo apt install redis-server  # Debian/Ubuntu
brew install redis             # macOS
sudo systemctl start redis

# Or use Docker
docker run -d --name redis-cutly -p 6379:6379 redis:7-alpine
```

5. Configure environment variables:
```bash
# Create .env file with your configuration
# See .env.example or REDIS_SETUP.md for details
```

### Environment Variables

```env
# Required
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token

# Optional
ADMIN_MASTER=your_telegram_id
SESSION_STRING=your_session_string
SESSION_NAME=cutly
WORKERS=20

# Database (optional, defaults to SQLite)
DB_NAME=cutly
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432

# Redis Cache (recommended for production, handles 1000+ concurrent users)
REDIS_ENABLED=true
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=  # Optional
```

> 💡 **Performance Tip**: Enable Redis cache for 10-100x faster response times and ability to handle 1000+ concurrent users.

## 📚 Architecture

### Design Patterns

- **Repository Pattern**: Services layer abstracts database operations
- **State Machine**: Conversation states for user interactions
- **Dependency Injection**: Configuration and dependencies injected
- **Separation of Concerns**: Clear separation between layers

### Layers

1. **App Layer** (`app/`): Bot initialization and configuration
2. **Core Layer** (`core/`): Database models and state management
3. **Service Layer** (`services/`): Business logic and data operations
4. **Utils Layer** (`utils/`): Reusable utilities and helpers

### Async Best Practices

- ✅ All I/O operations are async
- ✅ No blocking calls in async functions
- ✅ Proper error handling with try/except
- ✅ Rate limiting for broadcasts
- ✅ Concurrent operations with `asyncio.gather`
- ✅ Semaphores for resource management

## 🔧 Usage

### Running the Bot

```bash
python main.py
```

### Development

For development with auto-reload:
```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Run with auto-reload
watchdog main.py
```

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📧 Support

For support, please open an issue or contact the maintainer.

## 🙏 Acknowledgments

- [Telethon](https://github.com/LonamiWebs/Telethon) - Telegram client library
- [Tortoise ORM](https://github.com/tortoise/tortoise-orm) - Async ORM
- [APScheduler](https://github.com/agronholm/apscheduler) - Task scheduling
