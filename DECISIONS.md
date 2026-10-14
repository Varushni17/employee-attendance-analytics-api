# DECISIONS.md

1. **Indexes.** I use a unique index on employee code to prevent duplicate employees and a unique compound index on employee code and date to prevent duplicate daily attendance records. The employee/date index supports filtering attendance by employee and sorting by date. The date/employee index supports date-based listing and sorting. Other indexes support department employee lookups, joined-date filtering, and status/date queries. I would avoid adding indexes without a clear query benefit because every extra index takes storage and slows writes.

2. **Punch-in race.** If two identical punch-in requests arrive together, both may initially check that no record exists. The unique employee/date index allows only one insert to succeed. The other request receives a duplicate-key error, which the API converts to HTTP 409 Conflict, preventing duplicate attendance records.

3. **Ties.** The leaderboard should give employees with equal late-minute totals the same rank. Employees tied at the cutoff should be handled consistently with the API contract. The ranking and limit must be applied in the intended order.

4. **Headcount.** The department summary starts from employee records and adds attendance statistics when available. This keeps eligible employees in the headcount even when they have no attendance logs in the selected period.

5. **Future improvement.** For 100 times more data, I would measure query performance using realistic data, review execution plans, optimise aggregation pipelines and indexes based on measured bottlenecks, and add automated tests for edge cases and concurrent requests.