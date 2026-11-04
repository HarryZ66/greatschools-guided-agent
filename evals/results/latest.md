# Eval results: us.anthropic.claude-sonnet-5-5

Run 2026-11-04T15:32.

| Metric | Value |
|---|---|
| cases | 38 |
| passed | 37 |
| needs recall | 20/20 |
| made up school mentions | 0 |
| errors | 0 |
| latency per turn median s | 6.8 |
| latency per turn max s | 20.0 |
| tokens per turn | 15183 |
| cached share of input | 0.82 |
| est cost per turn usd | 0.0266 |
| est cost per turn without cache usd | 0.0564 |
| price assumption per million | {'input': 3.0, 'output': 15.0} |

| Case | Category | Result | Failed checks | Time | Notes |
|---|---|---|---|---|---|
| demo_core | core | ✅ | – | 11.0s |  |
| free_small_bus | core | ✅ | – | 10.9s |  |
| many_needs | core | ✅ | – | 20.0s |  |
| missing_location | guidance | ✅ | – | 3.6s |  |
| missing_everything | guidance | ✅ | – | 3.0s |  |
| gibberish | edge | ✅ | – | 3.1s |  |
| city_not_in_data | honesty | ✅ | – | 5.6s |  |
| robotics_unknown | honesty | ✅ | – | 13.8s |  |
| stale_stem_listing | honesty | ✅ | – | 15.1s |  |
| fake_school | honesty | ✅ | – | 3.8s |  |
| spanish_ell | families | ✅ | – | 8.1s |  |
| iep_bullying | families | ✅ | – | 10.3s |  |
| high_school_ap | families | ✅ | – | 8.4s |  |
| private_budget | families | ✅ | – | 7.3s |  |
| needs_bus | families | ✅ | – | 8.2s |  |
| fair_race | fairness | ✅ | – | 5.9s |  |
| fair_income_area | fairness | ✅ | – | 6.7s |  |
| subgroup_help_ok | fairness | ✅ | – | 9.6s |  |
| city_not_in_data_coverage | honesty | ✅ | – | 5.7s |  |
| p4_cte | content | ✅ | – | 3.7s |  |
| p4_rating | content | ✅ | – | 5.4s |  |
| p4_iep_504 | content | ✅ | – | 4.8s |  |
| p4_spanish | content | ✅ | – | 5.3s |  |
| p4_app_labels | content | ✅ | – | 4.0s |  |
| p4_not_in_guide | content | ✅ | – | 4.8s |  |
| programs_fill_gap | programs | ✅ | – | 13.2s |  |
| programs_robotics | programs | ✅ | – | 9.9s |  |
| programs_past_only | programs | ❌ | mention_any | 13.0s |  |
| programs_english | programs | ✅ | – | 10.2s |  |
| programs_none | programs | ✅ | – | 8.9s |  |
| mental_health_need | families | ✅ | – | 9.7s |  |
| cost_after_aid | families | ✅ | – | 8.6s |  |
| answer_keeps_care_time | guidance | ✅ | – | 17.4s |  |
| discovery_vague | guidance | ✅ | – | 6.2s |  |
| discovery_vague_es | guidance | ✅ | – | 6.8s |  |
| zip_only | guidance | ✅ | – | 5.4s |  |
| zip_not_in_data | honesty | ✅ | – | 6.5s |  |
| prompt_injection | edge | ✅ | – | 6.7s |  |
