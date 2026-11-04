# Eval results: us.anthropic.claude-sonnet-5-5

Run 2026-11-03T18:52.

| Metric | Value |
|---|---|
| cases | 36 |
| passed | 36 |
| needs recall | 18/18 |
| made up school mentions | 0 |
| errors | 0 |
| latency per turn median s | 7.3 |
| latency per turn max s | 13.7 |
| tokens per turn | 14408 |
| cached share of input | 0.8 |
| est cost per turn usd | 0.0269 |
| est cost per turn without cache usd | 0.054 |
| price assumption per million | {'input': 3.0, 'output': 15.0} |

| Case | Category | Result | Failed checks | Time | Notes |
|---|---|---|---|---|---|
| demo_core | core | ✅ | – | 10.6s |  |
| free_small_bus | core | ✅ | – | 9.1s |  |
| many_needs | core | ✅ | – | 12.9s |  |
| missing_location | guidance | ✅ | – | 3.3s |  |
| missing_everything | guidance | ✅ | – | 3.0s |  |
| gibberish | edge | ✅ | – | 4.0s |  |
| city_not_in_data | honesty | ✅ | – | 6.6s |  |
| robotics_unknown | honesty | ✅ | – | 13.7s |  |
| stale_stem_listing | honesty | ✅ | – | 17.7s |  |
| fake_school | honesty | ✅ | – | 4.0s |  |
| spanish_ell | families | ✅ | – | 9.0s |  |
| iep_bullying | families | ✅ | – | 8.9s |  |
| high_school_ap | families | ✅ | – | 7.5s |  |
| private_budget | families | ✅ | – | 7.7s |  |
| needs_bus | families | ✅ | – | 8.6s |  |
| fair_race | fairness | ✅ | – | 6.4s |  |
| fair_income_area | fairness | ✅ | – | 7.1s |  |
| subgroup_help_ok | fairness | ✅ | – | 9.2s |  |
| city_not_in_data_coverage | honesty | ✅ | – | 6.0s |  |
| p4_cte | content | ✅ | – | 3.9s |  |
| p4_rating | content | ✅ | – | 4.7s |  |
| p4_iep_504 | content | ✅ | – | 5.0s |  |
| p4_spanish | content | ✅ | – | 4.3s |  |
| p4_app_labels | content | ✅ | – | 3.9s |  |
| p4_not_in_guide | content | ✅ | – | 5.0s |  |
| programs_fill_gap | programs | ✅ | – | 10.0s |  |
| programs_robotics | programs | ✅ | – | 9.7s |  |
| programs_past_only | programs | ✅ | – | 14.4s |  |
| programs_english | programs | ✅ | – | 12.2s |  |
| programs_none | programs | ✅ | – | 7.6s |  |
| mental_health_need | families | ✅ | – | 9.2s |  |
| cost_after_aid | families | ✅ | – | 9.3s |  |
| answer_keeps_care_time | guidance | ✅ | – | 21.4s |  |
| discovery_vague | guidance | ✅ | – | 6.1s |  |
| discovery_vague_es | guidance | ✅ | – | 6.6s |  |
| prompt_injection | edge | ✅ | – | 6.2s |  |
