# Procurement runtime task evidence
Root implemented Task 2 in supply.py and tests/test_procurement_supply.py.
Red: initial eight tests failed due missing purchase support. Green: 36 procurement+existing supply tests pass.
Coverage: purchase-only threshold, purchase periodic, own trigger eligibility, partial transfer+purchase, shorter purchase/tie transfer, pending not double counted, zero lead/fresh parent-child creation, demand+buffer, later purchase tick converts unallocated transfer promise, upstream procurement sponsors downstream, differing targets.
Contract: supply.created_ids and created_counts record entire new subtrees; engine must include in conservation. New roots created held at receipt, then supply.return_part/on_stock called. on_stock handles PM clocks registration (retirement agent). Existing no-purchase snapshot untouched. Orders common across transfer/purchase; purchases record batch amounts and physical IDs after arrival only. No actual supplier/financial action.
Potential review areas: same-time stabilization, differing policy triggers/targets, pending promises and sponsor removal, generated quantities bounds, purchases before horizon arriving after horizon.
