# 🕷️ Configurable Scraping System

A production-ready scraping engine built with **Django REST Framework**, **Celery**, and **Docker**. It allows for dynamic management of data sources via a REST API and automated background scraping on a configurable schedule.

## 🚀 Quick Start

1. **Clone & Setup:**
   ```bash
   git clone <repo-url>
   cd Configurable-Scraping-System
   cp .env.example .env
   ```

2. **Launch Infrastructure:**
   ```bash
   docker compose up --build -d
   ```

3. **Initialize Database:**
   ```bash
   docker compose exec web python manage.py migrate
   docker compose exec web python manage.py createsuperuser  # Optional
   ```

The API is available at `http://localhost:8000/api/` and interactive Swagger documentation at `http://localhost:8000/api/docs/`.

## 📡 How the API Works

### 1. Authentication
Write operations require an Authentication Token. Obtain one via `POST /api/auth/token/` and include it in headers: `Authorization: Token <your_token>`.

### 2. Defining Sources
Add a scraping target by sending a `POST` to `/api/sources/`.
- **`extraction_type`**: Choose `html` (CSS selectors) or `json` (dotted paths).
- **`rules`**: Define fields to extract (e.g., `{"price": {"selector": ".price-tag", "type": "single", "format": "decimal"}}`).
- **`frequency_minutes`**: Set the scraping interval.

### 3. Execution & Results
- **Automated**: Background workers check for overdue sources every minute.
- **Manual**: Trigger an immediate scrape via `POST /api/sources/{id}/run_now/`.
- **Results**: Access all collected data snapshots at `/api/results/`.

---
*Powered by Python 3.11, PostgreSQL, Redis, and Celery.*