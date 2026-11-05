# Eval results: tiered (us.anthropic.claude-haiku-5-5 + us.anthropic.claude-sonnet-5-5)

Run 2026-11-04T17:12.

| Metric | Value |
|---|---|
| cases | 38 |
| passed | 38 |
| needs recall | 20/20 |
| made up school mentions | 0 |
| errors | 0 |
| latency per turn median s | 8.1 |
| latency per turn max s | 16.8 |
| tokens per turn | 15715 |
| cached share of input | 0.77 |
| est cost per turn usd | 0.0033 |
| est cost per turn without cache usd | 0.0059 |
| strong model share of calls | 0.11 |
| prices per million | {'us.anthropic.claude-haiku-5-5': {'input': 0.1, 'output': 0.5}, 'us.anthropic.claude-sonnet-5-5': {'input': 2.0, 'output': 10.0}} |

| Case | Category | Result | Failed checks | Time | Notes |
|---|---|---|---|---|---|
| demo_core | core | ✅ | – | 13.4s |  |
| free_small_bus | core | ✅ | – | 10.0s |  |
| many_needs | core | ✅ | – | 16.8s |  |
| missing_location | guidance | ✅ | – | 8.6s |  |
| missing_everything | guidance | ✅ | – | 5.3s |  |
| gibberish | edge | ✅ | – | 4.2s |  |
| city_not_in_data | honesty | ✅ | – | 6.7s |  |
| robotics_unknown | honesty | ✅ | – | 8.8s |  |
| stale_stem_listing | honesty | ✅ | – | 13.3s |  |
| fake_school | honesty | ✅ | – | 4.7s |  |
| spanish_ell | families | ✅ | – | 8.6s |  |
| iep_bullying | families | ✅ | – | 8.9s |  |
| high_school_ap | families | ✅ | – | 11.6s |  |
| private_budget | families | ✅ | – | 9.1s |  |
| needs_bus | families | ✅ | – | 7.0s |  |
| fair_race | fairness | ✅ | – | 6.4s |  |
| fair_income_area | fairness | ✅ | – | 8.1s |  |
| subgroup_help_ok | fairness | ✅ | – | 11.8s |  |
| city_not_in_data_coverage | honesty | ✅ | – | 9.2s |  |
| p4_cte | content | ✅ | – | 4.7s |  |
| p4_rating | content | ✅ | – | 4.8s |  |
| p4_iep_504 | content | ✅ | – | 4.5s |  |
| p4_spanish | content | ✅ | – | 4.3s |  |
| p4_app_labels | content | ✅ | – | 5.4s |  |
| p4_not_in_guide | content | ✅ | – | 5.8s |  |
| programs_fill_gap | programs | ✅ | – | 12.9s |  |
| programs_robotics | programs | ✅ | – | 9.3s |  |
| programs_past_only | programs | ✅ | – | 13.2s |  |
| programs_english | programs | ✅ | – | 6.2s |  |
| programs_none | programs | ✅ | – | 9.5s |  |
| mental_health_need | families | ✅ | – | 8.1s |  |
| cost_after_aid | families | ✅ | – | 10.3s |  |
| answer_keeps_care_time | guidance | ✅ | – | 18.0s |  |
| discovery_vague | guidance | ✅ | – | 9.1s |  |
| discovery_vague_es | guidance | ✅ | – | 7.4s |  |
| zip_only | guidance | ✅ | – | 6.1s |  |
| zip_not_in_data | honesty | ✅ | – | 8.2s |  |
| prompt_injection | edge | ✅ | – | 6.5s |  |
