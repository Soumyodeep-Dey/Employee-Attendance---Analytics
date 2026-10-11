# Design decisions

1. **Indexes.** Unique emp_code and employee/date indexes enforce identity and one attendance record per day. Department/code supports employee listing; joined_on/department supports monthly headcount; department/joined_on supports filtered headcounts. Date/code and status/date/code support attendance filtering and ordering; employee/punch_in selects the latest eligible punch. Employee/date also serves monthly log lookups. I rejected indexing history: no endpoint searches it, and every correction would increase index maintenance. Actual queries and explain share index hints, verified against 100,000 records.

2. **Punch-in race.** Both requests read the employee and compute the same attendance date. Both attempt insertion. MongoDB's unique employee/date index permits one insert. That request returns 201; DuplicateKeyError becomes 409 for the other. A prior existence check is unnecessary.

3. **Ties.** MongoDB computes competition ranks before filtering rank <= limit. Everyone tied at the cutoff is returned, ordered by employee code within equal totals; the next rank skips positions.

4. **Headcount.** The summary starts from employees who joined by month-end, then looks up grouped attendance. Empty lookups contribute zero metrics while each employee still contributes one to headcount.

5. **100x data.** I would introduce maintained daily department summaries, measuring refresh cost and correction handling before choosing incremental updates.
