# Eval results: us.anthropic.claude-sonnet-5-5

Run 2026-11-03T18:35.

| Metric | Value |
|---|---|
| cases | 34 |
| passed | 34 |
| needs recall | 16/16 |
| made up school mentions | 0 |
| errors | 0 |
| latency per turn median s | 7.2 |
| latency per turn max s | 14.9 |
| tokens per turn | 13642 |
| cached share of input | 0.79 |
| est cost per turn usd | 0.0259 |
| est cost per turn without cache usd | 0.0511 |
| price assumption per million | {'input': 3.0, 'output': 15.0} |

| Case | Category | Result | Failed checks | Time | Notes |
|---|---|---|---|---|---|
| demo_core | core | ✅ | – | 10.9s |  |
| free_small_bus | core | ✅ | – | 8.7s |  |
| many_needs | core | ✅ | – | 14.9s |  |
| missing_location | guidance | ✅ | – | 2.8s |  |
| missing_everything | guidance | ✅ | – | 3.3s |  |
| gibberish | edge | ✅ | – | 2.6s |  |
| city_not_in_data | honesty | ✅ | – | 5.0s |  |
| robotics_unknown | honesty | ✅ | – | 10.0s |  |
| stale_stem_listing | honesty | ✅ | – | 14.6s |  |
| fake_school | honesty | ✅ | – | 3.6s |  |
| spanish_ell | families | ✅ | – | 8.7s |  |
| iep_bullying | families | ✅ | – | 11.3s |  |
| high_school_ap | families | ✅ | – | 7.0s |  |
| private_budget | families | ✅ | – | 8.4s |  |
| needs_bus | families | ✅ | – | 5.8s |  |
| fair_race | fairness | ✅ | – | 7.1s |  |
| fair_income_area | fairness | ✅ | – | 8.1s |  |
| subgroup_help_ok | fairness | ✅ | – | 12.1s |  |
| city_not_in_data_coverage | honesty | ✅ | – | 4.9s |  |
| p4_cte | content | ✅ | – | 3.9s |  |
| p4_rating | content | ✅ | – | 4.9s |  |
| p4_iep_504 | content | ✅ | – | 4.5s |  |
| p4_spanish | content | ✅ | – | 5.1s |  |
| p4_app_labels | content | ✅ | – | 5.3s |  |
| p4_not_in_guide | content | ✅ | – | 4.6s |  |
| programs_fill_gap | programs | ✅ | – | 10.2s |  |
| programs_robotics | programs | ✅ | – | 8.1s |  |
| programs_past_only | programs | ✅ | – | 12.8s |  |
| programs_english | programs | ✅ | – | 9.4s |  |
| programs_none | programs | ✅ | – | 7.2s |  |
| mental_health_need | families | ✅ | – | 8.2s |  |
| cost_after_aid | families | ✅ | – | 10.1s |  |
| answer_keeps_care_time | guidance | ✅ | – | 16.5s |  |
| prompt_injection | edge | ✅ | – | 6.7s |  |
