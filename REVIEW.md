# REVIEW.md

## Problems Found and Fixes Made

### 1. Late-Minute Calculation
The original late-minute calculation needed to handle the 10-minute grace period and overnight shifts correctly. I added `late_minutes()` along with shift-time helper functions to calculate late minutes based on the employee's shift start.

### 2. Work-Hour Calculation
The work-hour calculation needed to follow the required rounding rule. I added a `rounded()` helper using `Decimal` and `ROUND_HALF_UP` to get consistent results.

### 3. Overtime Calculation
Overtime needed to be calculated using the actual shift end time. I updated the calculation to handle overnight shifts and count overtime only when the extra time reaches at least 30 minutes.

### 4. Timezone Handling
Datetime values needed consistent timezone handling. I configured MongoDB to return timezone-aware datetimes and added helpers to convert between UTC and IST.

### 5. Employee Input Validation
Employee details needed stronger validation. I added checks for employee codes, email addresses, shift times and joining dates. Extra fields are also rejected.

### 6. Employee Creation
Duplicate employee codes could cause problems when two requests arrived at nearly the same time. I added a unique index on employee codes and handled duplicate-key errors with HTTP 409.

### 7. Employee Listing and Pagination
The employee-listing logic needed the correct pagination offset and matching totals for department filters. I corrected the offset to `(page - 1) * page_size` and added sorting and pagination validation.

### 8. Punch-In
Punch-in needed to validate the employee and timestamp before saving attendance. I added `require_employee()`, timestamp validation and `record_day()` to handle attendance dates for overnight shifts.

A unique index on `(emp_code, date)` prevents duplicate attendance records when simultaneous punch-in requests occur.

### 9. Attendance Listing
Attendance listing needed validation for dates, status and date ranges. I added these checks, improved timestamp formatting and applied sorting and pagination in MongoDB.

### 10. Database Indexes
The database needed indexes to prevent duplicate records and support common queries. I added named indexes for employee codes and attendance filters.

### 11. Punch-Out
The original starter did not include the required punch-out operation. I added punch-out processing with timestamp checks, work-hour calculation, overtime calculation and half-day calculation.

### 12. Attendance Regularization
Attendance corrections needed validation and a record of what changed. I added regularization logic that recalculates derived attendance values and stores the changes, reason and person responsible in the history.

### 13. Monthly Employee Analytics
Monthly attendance statistics were missing. I added calculations for working days, present days, leave days, late count and attendance percentage.

### 14. Department Summary
Department-level attendance statistics were missing. I added a summary that calculates attendance metrics and includes eligible employees in headcount even if they have no attendance logs.

### 15. Late Leaderboard
The leaderboard needed to rank employees based on total late minutes while handling equal scores. I added aggregation and ranking logic that keeps employees tied at the cutoff rank.

### 16. Department Trend
The department trend needed to include dates without attendance records. I added MongoDB aggregation to generate missing dates, calculate daily attendance statistics and produce a seven-day moving average.

### 17. Query Explain Endpoint
The required query explain endpoint was missing. I added support for inspecting execution plans and index usage for the supported query types.

### 18. Health Check
The health endpoint needed to check whether MongoDB was reachable. I added a database ping and an HTTP 503 response when the database is unavailable.

## Things I Checked That Are Not Defects

- **10-minute grace period:** A punch-in exactly 10 minutes after shift start is not late because the delay must be greater than 10 minutes.
- **Weekend attendance:** Weekend records can still contribute to late and overtime totals, even though weekends are excluded from monthly working-day counts.
- **Employees without attendance logs:** Eligible employees should still be included in department headcount.
- **Unique attendance index:** The unique employee/date index is intentional because it prevents duplicate daily attendance records.
- **MongoDB `_id`:** This is an internal database field and does not need to be exposed as the employee's public identifier.

