# Eval results: us.anthropic.claude-sonnet-5-5

Run 2026-11-03T17:43.

| Metric | Value |
|---|---|
| cases | 33 |
| passed | 33 |
| needs recall | 16/16 |
| made up school mentions | 0 |
| errors | 0 |
| latency per turn median s | 6.9 |
| latency per turn max s | 14.5 |
| tokens per turn | 12364 |
| cached share of input | 0.79 |
| est cost per turn usd | 0.0245 |
| est cost per turn without cache usd | 0.0471 |
| price assumption per million | {'input': 3.0, 'output': 15.0} |

| Case | Category | Result | Failed checks | Time | Notes |
|---|---|---|---|---|---|
| demo_core | core | ✅ | – | 11.3s |  |
| free_small_bus | core | ✅ | – | 10.0s |  |
| many_needs | core | ✅ | – | 14.5s |  |
| missing_location | guidance | ✅ | – | 3.0s |  |
| missing_everything | guidance | ✅ | – | 3.1s |  |
| gibberish | edge | ✅ | – | 2.5s |  |
| city_not_in_data | honesty | ✅ | – | 4.7s |  |
| robotics_unknown | honesty | ✅ | – | 7.5s |  |
| stale_stem_listing | honesty | ✅ | – | 13.1s |  |
| fake_school | honesty | ✅ | – | 3.8s |  |
| spanish_ell | families | ✅ | – | 7.5s |  |
| iep_bullying | families | ✅ | – | 10.5s |  |
| high_school_ap | families | ✅ | – | 7.4s |  |
| private_budget | families | ✅ | – | 7.2s |  |
| needs_bus | families | ✅ | – | 6.6s |  |
| fair_race | fairness | ✅ | – | 7.0s |  |
| fair_income_area | fairness | ✅ | – | 6.7s |  |
| subgroup_help_ok | fairness | ✅ | – | 10.3s |  |
| city_not_in_data_coverage | honesty | ✅ | – | 5.7s |  |
| p4_cte | content | ✅ | – | 4.4s |  |
| p4_rating | content | ✅ | – | 5.1s |  |
| p4_iep_504 | content | ✅ | – | 5.1s |  |
| p4_spanish | content | ✅ | – | 5.2s |  |
| p4_app_labels | content | ✅ | – | 4.6s |  |
| p4_not_in_guide | content | ✅ | – | 4.3s |  |
| programs_fill_gap | programs | ✅ | – | 10.5s |  |
| programs_robotics | programs | ✅ | – | 10.0s |  |
| programs_past_only | programs | ✅ | – | 13.9s |  |
| programs_english | programs | ✅ | – | 7.3s |  |
| programs_none | programs | ✅ | – | 6.9s |  |
| mental_health_need | families | ✅ | – | 8.4s |  |
| cost_after_aid | families | ✅ | – | 8.1s |  |
| prompt_injection | edge | ✅ | – | 6.7s |  |
