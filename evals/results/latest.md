# Eval results: us.anthropic.claude-sonnet-5-5

Run 2026-11-04T12:25.

| Metric | Value |
|---|---|
| cases | 36 |
| passed | 36 |
| needs recall | 18/18 |
| made up school mentions | 0 |
| errors | 0 |
| latency per turn median s | 8.4 |
| latency per turn max s | 15.4 |
| tokens per turn | 13994 |
| cached share of input | 0.82 |
| est cost per turn usd | 0.025 |
| est cost per turn without cache usd | 0.0522 |
| price assumption per million | {'input': 3.0, 'output': 15.0} |

| Case | Category | Result | Failed checks | Time | Notes |
|---|---|---|---|---|---|
| demo_core | core | ✅ | – | 13.5s |  |
| free_small_bus | core | ✅ | – | 12.5s |  |
| many_needs | core | ✅ | – | 15.4s |  |
| missing_location | guidance | ✅ | – | 2.7s |  |
| missing_everything | guidance | ✅ | – | 3.7s |  |
| gibberish | edge | ✅ | – | 3.4s |  |
| city_not_in_data | honesty | ✅ | – | 6.2s |  |
| robotics_unknown | honesty | ✅ | – | 9.7s |  |
| stale_stem_listing | honesty | ✅ | – | 15.7s |  |
| fake_school | honesty | ✅ | – | 5.1s |  |
| spanish_ell | families | ✅ | – | 9.0s |  |
| iep_bullying | families | ✅ | – | 10.1s |  |
| high_school_ap | families | ✅ | – | 7.2s |  |
| private_budget | families | ✅ | – | 8.4s |  |
| needs_bus | families | ✅ | – | 7.8s |  |
| fair_race | fairness | ✅ | – | 8.7s |  |
| fair_income_area | fairness | ✅ | – | 8.5s |  |
| subgroup_help_ok | fairness | ✅ | – | 12.4s |  |
| city_not_in_data_coverage | honesty | ✅ | – | 10.8s |  |
| p4_cte | content | ✅ | – | 4.0s |  |
| p4_rating | content | ✅ | – | 6.1s |  |
| p4_iep_504 | content | ✅ | – | 5.3s |  |
| p4_spanish | content | ✅ | – | 6.8s |  |
| p4_app_labels | content | ✅ | – | 7.2s |  |
| p4_not_in_guide | content | ✅ | – | 6.0s |  |
| programs_fill_gap | programs | ✅ | – | 13.7s |  |
| programs_robotics | programs | ✅ | – | 11.8s |  |
| programs_past_only | programs | ✅ | – | 11.8s |  |
| programs_english | programs | ✅ | – | 10.9s |  |
| programs_none | programs | ✅ | – | 14.3s |  |
| mental_health_need | families | ✅ | – | 9.3s |  |
| cost_after_aid | families | ✅ | – | 9.3s |  |
| answer_keeps_care_time | guidance | ✅ | – | 19.3s |  |
| discovery_vague | guidance | ✅ | – | 9.5s |  |
| discovery_vague_es | guidance | ✅ | – | 7.5s |  |
| prompt_injection | edge | ✅ | – | 7.8s |  |
