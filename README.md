# NearHub – Student Accommodation & Dining Platform

A Flask + MySQL web application with three account types: Student, Hostel Owner, and Mess Owner.

## Features in this starter release
- Separate role-based registration and login; password hashing and Flask sessions.
- Students browse and filter hostel and mess listings.
- Hostel owners create listings and approve/reject booking requests.
- Mess owners create listings, publish menu items, create meal plans, and approve/reject subscription requests.
- Students track booking/subscription states and receive in-app notifications.
- Reviews are accepted only after a completed booking/subscription (an owner workflow to mark completed is still to be added).

## Requirements
- Python 3.12
- MySQL Server 8.x (Workbench is only the GUI; Server must be installed and running)
- VS Code

## Setup on Windows PowerShell
1. Open this folder in VS Code.
2. Create/activate a virtual environment:
   ```powershell
   py -3.12 -m venv venv
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\venv\Scripts\Activate.ps1
   ```
3. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
4. In MySQL Workbench, create/select the database:
   ```sql
   CREATE DATABASE IF NOT EXISTS nearhub_platform
   CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```
5. Copy `.env.example` to `.env`, then enter your local MySQL root password in `.env`. Never upload `.env`.
6. Initialize tables:
   ```powershell
   flask --app app init-db
   ```
7. Run:
   ```powershell
   python app.py
   ```
8. Open http://127.0.0.1:5000

## Important scope notes
This is a runnable academic MVP foundation, not a production marketplace. Before a real deployment, add CSRF protection, email/phone verification, rate limiting, secure production secrets, audit logging, image upload validation, owner verification/document workflows, and privacy/legal review. Booking date availability and meal-plan capacity are not yet enforced transactionally; pending requests do not reserve capacity. Add atomic capacity checks before real-world use. There is no payment gateway or admin module, as specified.
