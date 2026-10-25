# policy

`policy.json`: the farm's name, the approvers, the harvest start time (a harvest is an entry at this time), the morning digest time, crop aliases and the card templates. `policy.py` loads it and refuses a template that uses any field outside the contract's card fields. Run `python3 policy/policy.py` after an edit.
