1. FastAPI Backend
Registration APIs
POST /register - Register new users

GET /get-total-users - Get total user count

GET /get-verified-users-count - Get verified users count

GET /get-pending-verification-count - Get pending verification count

GET /registered-today - Get users registered today

GET /regisetered-this-week - Get users registered this week (typo in route name)

Dashboard APIs
GET /dashboard/stats - Get dashboard statistics

GET /dashboard/registration-trend - Get 7-day registration trend

GET /dashboard/verification-status - Get verification status distribution

GET /dashboard/ai-performance - Get AI performance metrics

GET /dashboard/customer-status - Get customer onboarding status

Chatbot APIs
POST /chatbot/query - Send query to chatbot

GET /chatbot/status - Get chatbot status

GET /chatbot/test - Test AI API connectivity

Email System APIs
GET /email/unread - Get unread emails from IMAP

POST /email/send - Send email via SMTP

GET /email/statistics - Get email statistics (last 30 days)

GET /email/templates - Get email templates

User Management APIs
GET /users/all - Get all users with details

GET /users/{user_id} - Get specific user details

PUT /users/{user_id} - Update user information

DELETE /users/{user_id} - Delete user and associated data

GET /users/{user_id}/conversations - Get user conversations

Settings APIs
GET /settings/system-status - Get system component status

GET /settings/configuration - Get system configuration

2. Additional APIs Required for Full Frontend Functionality

POST /chatbot/file-upload - Handle file uploads with chatbot queries

GET /dashboard/recent-activities - Get recent system activities

POST /users/bulk-actions - Bulk operations on multiple users

GET /email/conversation-thread/{user_email} - Get email conversation thread

POST /settings/update-configuration - Update system settings

GET /analytics/export - Export analytics data
