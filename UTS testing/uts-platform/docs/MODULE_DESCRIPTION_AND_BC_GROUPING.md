# Module description filter + Business-flow BC grouping

## 1) Description in config/app-input.json

Set `description` to target a module. Leave empty for full application flow.

Examples:
- "Create Lead module test cases" -> Create Lead only
- "Admin module testing" -> Admin only
- "" -> complete application flow

Credentials currently configured:
- URL: http://127.0.0.1:8765/index.html
- Username: admin_user
- Password: Pass@123

## 2) Business Component grouping

Before: one BC per Excel/UI step
After: BC_Launch_Application -> BC_Login -> one BC for the business process (all related steps)
