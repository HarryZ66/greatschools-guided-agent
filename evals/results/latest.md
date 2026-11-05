# Eval results: us.anthropic.claude-sonnet-5-5

Run 2026-11-05T00:23.

| Metric | Value |
|---|---|
| cases | 38 |
| passed | 38 |
| needs recall | 20/20 |
| made up school mentions | 0 |
| errors | 0 |
| latency per turn median s | 7.1 |
| latency per turn max s | 14.3 |
| tokens per turn | 13827 |
| cached share of input | 0.82 |
| est cost per turn usd | 0.0155 |
| est cost per turn without cache usd | 0.0336 |
| strong model share of calls | 1.0 |
| prices per million | {'us.anthropic.claude-sonnet-5-5': {'input': 2.0, 'output': 10.0}} |

| Case | Category | Result | Failed checks | Time | Notes |
|---|---|---|---|---|---|
| demo_core | core | ✅ | – | 13.7s |  |
| free_small_bus | core | ✅ | – | 9.9s |  |
| many_needs | core | ✅ | – | 14.3s |  |
| missing_location | guidance | ✅ | – | 7.3s |  |
| missing_everything | guidance | ✅ | – | 4.6s |  |
| gibberish | edge | ✅ | – | 3.2s |  |
| city_not_in_data | honesty | ✅ | – | 5.5s |  |
| robotics_unknown | honesty | ✅ | – | 11.0s |  |
| stale_stem_listing | honesty | ✅ | – | 12.8s |  |
| fake_school | honesty | ✅ | – | 4.3s |  |
| spanish_ell | families | ✅ | – | 10.4s |  |
| iep_bullying | families | ✅ | – | 9.6s |  |
| high_school_ap | families | ✅ | – | 7.2s |  |
| private_budget | families | ✅ | – | 7.8s |  |
| needs_bus | families | ✅ | – | 7.9s |  |
| fair_race | fairness | ✅ | – | 6.5s |  |
| fair_income_area | fairness | ✅ | – | 6.4s |  |
| subgroup_help_ok | fairness | ✅ | – | 9.9s |  |
| city_not_in_data_coverage | honesty | ✅ | – | 5.3s |  |
| p4_cte | content | ✅ | – | 5.5s |  |
| p4_rating | content | ✅ | – | 6.1s |  |
| p4_iep_504 | content | ✅ | – | 4.6s |  |
| p4_spanish | content | ✅ | – | 4.9s |  |
| p4_app_labels | content | ✅ | – | 5.5s |  |
| p4_not_in_guide | content | ✅ | – | 7.8s |  |
| programs_fill_gap | programs | ✅ | – | 9.3s |  |
| programs_robotics | programs | ✅ | – | 7.1s |  |
| programs_past_only | programs | ✅ | – | 14.4s |  |
| programs_english | programs | ✅ | – | 8.3s |  |
| programs_none | programs | ✅ | – | 6.3s |  |
| mental_health_need | families | ✅ | – | 11.3s |  |
| cost_after_aid | families | ✅ | – | 6.9s |  |
| answer_keeps_care_time | guidance | ✅ | – | 18.5s |  |
| discovery_vague | guidance | ✅ | – | 0.3s |  |
| discovery_vague_es | guidance | ✅ | – | 7.1s |  |
| zip_only | guidance | ✅ | – | 0.2s |  |
| zip_not_in_data | honesty | ✅ | – | 7.2s |  |
| prompt_injection | edge | ✅ | – | 5.9s |  |
