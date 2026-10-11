DECISIONS.md

1. Indexes. I created a unique index on employee code to prevent duplicate employees, and a unique compound index on employee code and date to prevent duplicate daily attendance records. Other indexes support department employee lookups, joined-date filtering, attendance date sorting, employee attendance history, and status/date queries. I would avoid adding indexes without checking query plans because extra indexes use storage and slow writes.

2. Punch-in race. If two identical punch-in requests arrive together, both may try to insert the same employee's attendance for the same date. The unique compound index allows only one insert. The other request receives a duplicate-key error, which the API converts to HTTP 409 Conflict.

3. Ties. The leaderboard sorts by total late minutes descending and employee code ascending. Employees tied at the cutoff can still appear because the code uses competition ranking and includes equal-ranked results.

4. Headcount. The department summary starts with employee records and then adds attendance statistics when available. Therefore, eligible employees with no attendance logs are still included in headcount.

5. Future improvement. For 100 times more data, I would review query plans with realistic data, improve analytics aggregation in MongoDB, and add automated tests for edge cases and concurrent requests.
