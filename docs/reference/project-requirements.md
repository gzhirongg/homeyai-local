# project_requirements.md

## Version Log
| Version | Date | Description |
|---------|------|-------------|
| 1.3 | 2026-05-13 | Geospatial analytics explorer: deterministic address + area amenity breakdown; MRT two-pass query. |
| 1.2 | 2026-03-16 | Updated Data Strategy to store all historical data in PostGIS & added Admin Data Catalog. |
| 1.1 | 2026-03-16 | Updated Data Storage Strategy to Hybrid Medallion Architecture (MinIO/S3 + PostGIS). |
| 1.0 | 2026-03-14 | Initial project requirements. |

## 1. Project Overview

**Project Title:** Interactive Website for Real Estate Price Prediction in Singapore  

This project aims to develop a web-based, AI-powered real estate valuation platform tailored specifically for Singapore's residential property market (HDB, Condo, Landed). The system integrates:

- Historical transaction data  
- Geospatial intelligence (MRT, schools, CBD distance)  
- Machine learning predictive models  
- Explainable AI (XAI)  
- Interactive dashboards and financial calculators  

The platform follows a **freemium subscription model** and emphasizes **transparency, interpretability, and user-centric design**.

---

## 2. System Architecture Overview

The system consists of three major layers:

1. **Data Layer (Hybrid Medallion Architecture)**
   - Data ingestion from government APIs
   - Data Lake (S3/MinIO): Bronze (Raw CSV/JSON) and Silver (Processed Parquet) tiers for ML/Archival
   - Serving Database (PostgreSQL/PostGIS): Fast, real-time lookups and spatial joins encompassing **ALL historical transactions**.

2. **Model Layer**
   - ML model training and evaluation
   - Explainability layer (SHAP, feature importance)
   - Periodic retraining and drift detection

3. **Application Layer**
   - Web frontend (responsive UI)
   - Backend API services
   - Authentication & subscription management
   - Visualization dashboards

---

## 3. User Stories

### Common User Stories (Actor Inheritance)

| Jira ID | User Story | Actors |
|----------|------------|--------|
| #1 | As a user, I want to view the estimated price range, so that I can assess property value before deciding to subscribe for detailed analysis. | Guest, Free User |
| #2 | As a user, I want to view product features and pricing plans, so that I can understand what the platform offers and its pricing plans. | Guest, Free User, Premium User |
| #3 | As a user, I want to view the demo video, so that I can see how the valuation system works in action. | Guest, Free User, Premium User |
| #4 | As a user, I want to search for unit valuation by postal code and property type, so that I can get a quick price estimate without registering. | Guest, Free User, Premium User |
| #5 | As a user, I want to view my personal details, so that I can check whether my details are up to date and correct. | Free User, Premium User |
| #6 | As a user, I want to update my personal details, so that I can keep my account information current and receive relevant updates. | Free User, Premium User |
| #7 | As a user, I want to delete my account, so that I can stop using this service at any time and have my data deleted. | Free User, Premium User |
| #8 | As a user, I want to save properties, so that I can check on the properties that I have generated valuations for. | Free User, Premium User |
| #9 | As a user, I want to view my saved properties, so that I can check on the properties that I have saved previously. | Free User, Premium User |
| #10 | As a user, I want to edit my saved properties, so that I can change some details like the saved name or notification preferences. | Free User, Premium User |
| #11 | As a user, I want to delete my saved property, so that I can remove unwanted properties from my list. | Free User, Premium User |
| #12 | As a user, I want to search in my saved properties, so that I can find the specific property that I want to see or edit. | Free User, Premium User |
| #13 | As a user, I want to input detailed property information (postal code, floor area, lease year, etc.), so that I can generate an accurate property valuation. | Free User, Premium User |
| #14 | As a user, I want to view the estimated property price, so that I can understand the current market value of a property. | Free User, Premium User |
| #15 | As a user, I want to view the confidence interval of the valuation, so that I can assess the reliability of the price prediction. | Free User, Premium User |
| #16 | As a user, I want to view the OneMap overlay, so that I can see the property location and surrounding amenities on a map. | Free User, Premium User |
| #17 | As a user, I want to view the distance to the nearest MRT station, so that I can evaluate the property's accessibility and transportation convenience. | Free User, Premium User |
| #18 | As a user, I want to view historical price graphs for the property area, so that I can understand price trends over time and make informed decisions. | Free User, Premium User |
| #19 | As a user, I want to use the mortgage calculator, so that I can estimate my monthly mortgage payments and assess affordability. | Free User, Premium User |
| #20 | As a user, I want to use the selling profit calculator, so that I can calculate potential profit by comparing purchase price with predicted selling price. | Free User, Premium User |

---

### Guest User Stories

| Jira ID | User Story | Actors |
|----------|------------|--------|
| #21 | As a Guest, I want to sign up with email or Google, so that I can access free valuation features and save my property searches. | Guest |
| #22 | As a Guest, I want to login into my account, so that I can access the personalized dashboard and tools associated with my specific user tier. | Guest |

---

### Free User Stories

| Jira ID | User Story | Actors |
|----------|------------|--------|
| #23 | As a Free User, I want to see how many free valuations I have remaining for the month, so that I can plan my searches accordingly. | Free User |

---

### Premium User Stories

| Jira ID | User Story | Actors |
|----------|------------|--------|
| #24 | As a premium subscriber, I want to generate and download a PDF valuation report, so that I can have a professional, offline document to share with clients or family. | Premium User |
| #25 | As a premium subscriber, I want to customize the report data (e.g., toggle specific metrics), so that the final PDF focuses only on the information relevant to my needs. | Premium User |
| #26 | As a premium subscriber, I want to inspect the AI's reasoning (SHAP values), so that I understand exactly why the model predicted a specific price (e.g., how much the 'Floor Level' contributed). | Premium User |
| #27 | As a premium subscriber, I want to compare the property against neighbors, so that I can see if the specific unit is priced fairly relative to similar nearby units. | Premium User |
| #28 | As a premium subscriber, I want to chat with the AI assistant, so that I can ask complex, natural-language questions about market trends without manually filtering charts. | Premium User |
| #29 | As a premium subscriber, I want to view the market sentiment score, so that I can gauge the general mood (bullish/bearish) of the Singapore property market from news and social data. | Premium User |

---

### System Admin User Stories

| Jira ID | User Story | Actors |
|----------|------------|--------|
| #30 | As a system admin, I want to manually trigger the HDB scraper, so that I can force an update of the latest resale transaction data immediately. | Admin User |
| #31 | As a system admin, I want to trigger the URA API fetch, so that the system can ingest the most recent private property prices from the government database. | Admin User |
| #32 | As a system admin, I want to execute the data processing scripts (cleaning and normalization), so that the raw data is formatted correctly before being fed into the AI model. | Admin User |
| #33 | As a system admin, I want to retrain the chosen ML model, so that the predictions stay accurate learning from the latest market trends. | Admin User |
| #34 | As a system admin, I want to adjust and tune the model's hyperparameters, so that I can optimize the accuracy and minimize errors as the dataset grows. | Admin User |
| #35 | As a system admin, I want to view performance metrics, so that I can validate if the current model is good enough for production. | Admin User |
| #36 | As a system admin, I want to check for data drift, so that I can be alerted if the market behavior has significant changes compared to the training data. | Admin User |
| #37 | As a system admin, I want to manage user subscriptions (e.g., upgrade/ban accounts), so that I can handle billing inquiries or restrict access for abusive users. | Admin User |
| #38 | As a system admin, I want to view usage analytics, so that I can monitor system load and see which features (e.g., Mortgage Calculator vs. Valuation) are most popular. | Admin User |
| #39 | As an admin user, I want to view user account details, so that I can inspect account information. | Admin User |
| #40 | As an admin user, I want to delete user accounts, so that I can remove accounts when necessary. | Admin User |
| #41 | As an admin user, I want to search user accounts, so that I can locate specific users quickly. | Admin User |
| #42 | As an admin user, I want to edit website content, so that I can update text, images, or videos. | Admin User |
| #43 | As an admin user, I want to view a Data Catalog, so that I can inspect all datasets stored across the MinIO Data Lake and PostgreSQL databases. | Admin User |
| #44 | As an admin user, I want to login, so that I can access administrative functions. | Admin User |
| #45 | As an admin user, I want to logout, so that I can securely exit the system. | Admin User |

### 3.5 Geospatial Analytics (Explorer)

**Analytics trigger rules**

1. **Deterministic address** — Analytics that depend on a point location run only when the user supplies a **full 6-digit postal code** and/or a **resolved property name** (e.g. chosen from search). Coordinates are read from `hdb_address_enrichment_onemap` only (no user-supplied lat/lon). If enrichment exists but latitude/longitude are missing, the API returns a **non-error** payload with `no_coordinates: true` and message *Geographical Analysis Unavailable: No Lat-long*.
2. **Area (region / towns)** — When one or more **URA planning areas** (towns) and/or a **URA region** is selected, area analytics use the **polygon union** of those planning areas. Output includes **MRT** (`mrt_station_lines` within polygon) and **POI counts/lists** from `poi_locations` (schools, malls, supermarkets, parks, markets, PCN), with PCN vertex lists capped when dense.

**MRT retrieval (address mode)** — Two-pass sequence: (1) physical stations within configurable radius (default **2 km**) via PostGIS `ST_DWithin`; (2) enrich with pre-computed legs from `hdb_mrt_routes` (`LEFT JOIN`) for walk/drive/PT distance and time where available.

| Jira ID | User Story | Actors | Date Added | Last Modified |
|---------|------------|--------|-------------|---------------|
| #46 | As a user, I want to view nearby MRT stations and their walking/transit times for a fully resolved address, so that I can evaluate transport accessibility. | Free User, Premium User | 2026-05-13 | 2026-05-13 |
| #47 | As a user, I want to view all MRT stations within a selected URA planning area/region, so that I can compare transit access across different areas. | Free User, Premium User | 2026-05-13 | 2026-05-13 |
| #48 | As a user, I want to view a full amenity breakdown (schools, malls, parks, markets, PCN) for one or more selected planning areas, so that I can compare the liveability of different areas. | Free User, Premium User | 2026-05-13 | 2026-05-13 |

## 5. Data Sources

| Source | Purpose |
|--------|----------|
| Data.gov.sg | HDB resale transactions |
| URA API | Private residential transactions |
| URA REALIS (Optional Paid) | Expanded property datasets |
| OneMap API | Distance & geospatial overlays |
| Google Maps API | Distance fallback |

---

## 4. Tech Stack

### Frontend
- React.js / Next.js
- Tailwind CSS
- Chart.js / ECharts / Plotly

### Backend
- Python (FastAPI / Flask)
- REST API architecture

### Machine Learning
- Scikit-learn
- XGBoost / LightGBM
- PyGAM (for GAMs)
- SHAP library

### Database & Storage
- PostgreSQL with PostGIS (Serving layer for active data & spatial joins)
- MinIO (Self-hosted S3-compatible Data Lake for Bronze/Silver ML data)

### Infrastructure
- Oracle Cloud VM (ARM)
- Docker Compose
- Tailscale VPN

---

## 5. Non-Functional Requirements

### Performance
- <3 seconds response time (normal usage)
- <10 seconds during peak (100 concurrent users)

### Scalability
- Support 5–10 users (demo)
- Up to 10GB storage (pilot)

### Availability
- 24/7 uptime
- Maintenance <4 hours/month
- Load balancing enabled

### Security
- Bcrypt password hashing
- Encryption in transit (HTTPS)
- Optional MFA
- Secure SDLC

### Reliability
- Error handling
- Logging
- API failure recovery

### Maintainability
- Modular architecture
- Git version control
- Unit + integration testing
- Clear documentation

---

## 6. Regulatory & Compliance Requirements

- PDPA (Singapore)
- GDPR principles:
  - Data minimization
  - Right to access
  - Right to delete
- ISO27001 considerations
- Terms of Service
- Subject Access Request mechanism

---

## 7. Business Model

### Freemium
- 3 free searches/day

### Subscription
- Advantage: $29.90/month
- Enterprise: $299/year

---

## 8. Out-of-Scope

- Commercial property valuation
- Rental yield modeling (future expansion)
- Property listing marketplace

---

## 9. Development Methodology

- Agile Scrum
- Iterative model evaluation
- Continuous integration
- Monthly model retraining

---

# End of project_requirements.md
