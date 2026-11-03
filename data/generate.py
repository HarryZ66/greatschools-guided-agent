"""Generate synthetic Miami-area schools in the same format as the GreatSchools sample.

The organizers confirmed that AI-generated data in the sample's format is allowed. All names,
addresses, ratings and reviews are fictional; every record has "synthetic_generated": true.

    python data/generate.py --count 80 --seed 7 --out data/generated/schools_generated.json

Beyond the sample's fields, records carry three fields the docs need but the sample lacks:
  after_care_end_time  "HH:MM" when after-school care ends (with after_care_as_of)
  tuition              yearly tuition in USD, private schools only
  osp_as_of            when the school-reported profile (osp) was last updated
"""

import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

CITIES = [
    # name, county, lat, lon, zip prefix, district (id, name, city), weight
    ("Miami", "Miami-Dade County", 25.7617, -80.1918, "331", (13, "Miami-Dade County Public Schools", "Miami"), 18),
    ("Hialeah", "Miami-Dade County", 25.8576, -80.2781, "330", (13, "Miami-Dade County Public Schools", "Miami"), 8),
    ("Coral Gables", "Miami-Dade County", 25.7215, -80.2684, "331", (13, "Miami-Dade County Public Schools", "Miami"), 6),
    ("Doral", "Miami-Dade County", 25.8195, -80.3553, "331", (13, "Miami-Dade County Public Schools", "Miami"), 6),
    ("Kendall", "Miami-Dade County", 25.6793, -80.3173, "331", (13, "Miami-Dade County Public Schools", "Miami"), 7),
    ("Miami Gardens", "Miami-Dade County", 25.9420, -80.2456, "330", (13, "Miami-Dade County Public Schools", "Miami"), 6),
    ("North Miami", "Miami-Dade County", 25.8901, -80.1867, "331", (13, "Miami-Dade County Public Schools", "Miami"), 5),
    ("Miami Beach", "Miami-Dade County", 25.7907, -80.1300, "331", (13, "Miami-Dade County Public Schools", "Miami"), 4),
    ("Cutler Bay", "Miami-Dade County", 25.5808, -80.3468, "331", (13, "Miami-Dade County Public Schools", "Miami"), 4),
    ("Homestead", "Miami-Dade County", 25.4687, -80.4776, "330", (13, "Miami-Dade County Public Schools", "Miami"), 5),
    ("Hollywood", "Broward County", 26.0112, -80.1495, "330", (6, "Broward County Public Schools", "Fort Lauderdale"), 6),
    ("Fort Lauderdale", "Broward County", 26.1224, -80.1373, "333", (6, "Broward County Public Schools", "Fort Lauderdale"), 6),
]

NAME_WORDS = [
    "Tamarind Cove", "Kestrel Point", "Lanternfish", "Moonfish Bay", "Sea Grape", "Brightwater", "Heron Landing",
    "Saltmarsh", "Manatee Run", "Egret Hollow", "Osprey Ridge", "Driftwood Bay", "Seabreeze Park", "Starfish Lane",
    "Tidewater", "Bougainvillea", "Breakwater", "Sea Oat", "Ibis Creek", "Sandpiper Cove", "Coquina", "Gumbo Limbo",
    "Firebush", "Silver Mullet", "Pelican Reach", "Mangrove Trail", "Sunfish", "Wavecrest", "Coralbean", "Sabal Bend",
    "Calusa Point", "Key Lime Grove", "Lighthouse Row", "Spoonbill", "Sawgrass Hollow", "Bayfront Commons",
    "Royal Tern", "Seastar", "Cocoplum", "Jacaranda Way", "Paradise Palm", "Blue Heron Glen", "Morning Tide",
    "Lagoon Park", "Sea Lavender", "Saltwind", "Bayou Sol", "Harborlight", "Anchor Point", "Clearwater Gate",
    "Sea Turtle Cove", "Hibiscus Row", "Trade Wind", "Pine Island Way", "Sunray", "Riverbend Palms", "Palm Lantern",
    "Coastline", "Marlin Way", "Dolphin Reach", "Sea Fan", "Wild Lime", "Golden Shore", "Mangrove Bend",
    "Seashell Commons", "North Star Bay", "Cypress Lantern", "Zephyr Park", "Laurel Oak Bay", "Sandy Cove",
    "Seaglass", "Banyan Lantern", "Aqua Vista", "Halcyon Bay", "Sunrise Wharf", "Cormorant", "Bayline", "Cay Point",
    "Tarpon Bend", "Mariposa Bay", "Sea Mist", "Esperanza", "Brisa Park", "Luz del Mar", "Ceiba Grove",
]
STREETS = ["Lantern Avenue", "Coral Way", "Bay Street", "Palm Drive", "Tide Road", "Harbor Lane", "Seaview Boulevard",
           "Mango Street", "Ocean Court", "Sunset Terrace", "Heron Drive", "Ibis Lane", "Sailfish Road"]

TOPICS = ["Leadership", "ELL", "Belonging / Inclusion", "Gifted / Advanced Learning", "Teachers / Staff",
          "Homework / Assignments", "Mental Health", "Special Ed / IEP", "Bullying / Safety", "Other", "Sports",
          "STEM / Coding"]
SENTENCES = {
    ("Teachers / Staff", "positive"): ["The teachers are patient, kind and very professional.",
                                       "Teachers keep parents updated on progress and are easy to reach."],
    ("Teachers / Staff", "negative"): ["There were long stretches with substitutes instead of a regular teacher.",
                                       "The school feels understaffed."],
    ("Bullying / Safety", "positive"): ["Our child feels safe here and the staff deal with problems quickly.",
                                        "The campus is secure and pickup is well supervised."],
    ("Bullying / Safety", "negative"): ["Bullying was reported several times and nothing was done.",
                                        "We did not feel the school took safety concerns seriously."],
    ("STEM / Coding", "positive"): ["The science and robotics programs are a real highlight.",
                                    "Our daughter loves the coding club and the science fair."],
    ("STEM / Coding", "negative"): ["Science classes feel like an afterthought.",
                                    "There is very little hands-on science or technology."],
    ("Special Ed / IEP", "positive"): ["They followed our son's IEP closely and communicated every step.",
                                       "The special education team is caring and well organized."],
    ("Special Ed / IEP", "negative"): ["It was a struggle to get our child's IEP followed.",
                                       "Support for students with learning differences is limited."],
    ("ELL", "positive"): ["Staff speak Spanish and help families who are still learning English.",
                          "Our child learned English quickly with the support here."],
    ("ELL", "negative"): ["Communication in Spanish was hard to get.", "English learners do not get much extra help."],
    ("Homework / Assignments", "positive"): ["Teachers explain homework clearly so kids can work on their own."],
    ("Homework / Assignments", "negative"): ["The homework load is heavy and not well explained."],
    ("Leadership", "positive"): ["The principal is visible, friendly and listens to parents."],
    ("Leadership", "negative"): ["Problems get brought up at meetings but nothing changes.",
                                 "The administration only cares about appearances."],
    ("Sports", "positive"): ["The sports teams are a great way for kids to make friends."],
    ("Sports", "negative"): ["There are very few sports options."],
    ("Mental Health", "positive"): ["The counselors helped our child through a hard year."],
    ("Mental Health", "negative"): ["There is not enough counseling support."],
    ("Belonging / Inclusion", "positive"): ["Every family feels welcome here."],
    ("Belonging / Inclusion", "negative"): ["Some families feel left out of school events."],
    ("Gifted / Advanced Learning", "positive"): ["The advanced classes keep our child challenged."],
    ("Gifted / Advanced Learning", "negative"): ["Advanced students are not challenged enough."],
    ("Other", "positive"): ["Pickup and drop-off are well organized.", "The front office is friendly and helpful."],
    ("Other", "negative"): ["Calls and emails often go unanswered.", "Pickup is chaotic every day."],
}
OPENERS = {"positive": ["We have been really happy with this school.", "This school has been a good fit for my child."],
           "negative": ["Unfortunately this school has not worked out for us.", "We are looking at other options for next year."]}
CLOSERS = {"positive": ["Highly recommended.", "Thank you to everyone who makes this school what it is."],
           "negative": ["Think carefully before choosing this school.", "Parents should visit and ask a lot of questions before enrolling."]}

CLUBS = ["art_club", "arts_crafts", "science_club", "math_club", "chess", "book_club", "drama_club", "game_club",
         "yearbook", "student_govt", "yoga", "community_service"]
FAMILY = ["academic_nights", "parent_surveys", "parent_teacher_conf", "progress_report", "report_cards", "sms_email",
          "website_apps", "parenting_classes", "in_person_translation", "phone_translation", "home_lang"]
MENTAL = ["anti_bullying", "mental_health_specialists", "positive_intervention", "school_counselors", "social_workers"]
SPORTS = ["soccer", "basketball", "volleyball", "cross_country", "track", "flag_football", "pe_classes", "softball"]
AP = ["Biology", "Calculus AB", "English Language and Composition", "Spanish Language and Culture",
      "US History", "Computer Science Principles", "Psychology"]


def demo_schools() -> list[dict]:
    """Hand-designed schools for the demo query: middle school near Miami, STEM, care until 6pm.

    They make a real trade-off: the strongest STEM school's care ends at 5pm, and each school
    with care until 6pm has a different catch the agent should surface.
    """
    return [
        dict(name="Tamarind Cove STEM Academy", entity_type="charter", levels=["e", "m"], city="Miami",
             summary=9, stem=True, care="17:00", ratio=14, bus=True, reviews=(12, 0.85), profile_age_days=60),
        dict(name="Kestrel Point Middle School", entity_type="public", levels=["m"], city="Miami",
             summary=6, stem=False, clubs=["science_club"], care="18:00", ratio=23, bus=True,
             reviews=(14, 0.45), recent_safety_negative=True, profile_age_days=90),
        dict(name="Lanternfish K-8 Center", entity_type="public", levels=["p", "e", "m"], city="Hialeah",
             summary=7, stem=True, care="18:30", ratio=18, bus=True, reviews=(9, 0.7), ell="high",
             profile_age_days=980),  # STEM listing is from early 2024: stale
        dict(name="Brightwater Preparatory School", entity_type="private", levels=["e", "m"], city="Coral Gables",
             summary=None, stem=True, care="18:00", ratio=11, bus=False, tuition=16500, reviews=(7, 0.8),
             profile_age_days=120),
        dict(name="Moonfish Bay Charter School", entity_type="charter", levels=["m"], city="Doral",
             summary=None, stem=True, care="18:00", ratio=52, bus=False, reviews=(1, 1.0), profile_age_days=30,
             enrollment=1),  # new school: no rating yet, bad ratio and enrollment values
        dict(name="Sea Grape Middle School", entity_type="public", levels=["m"], city="Miami Gardens",
             summary=5, profile=False, reviews=(4, 0.5)),
    ]


class Generator:
    def __init__(self, seed: int, today: datetime):
        self.rng = random.Random(seed)
        self.today = today
        self.used_names: set[str] = set()
        self.used_ids: set[int] = set()

    # ------------------------------------------------------------ small helpers

    def _iso(self, dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%S-07:00")

    def _new_id(self) -> int:
        while True:
            i = self.rng.randint(100000, 199999)
            if i not in self.used_ids:
                self.used_ids.add(i)
                return i

    def _name(self, entity_type: str, levels: list[str]) -> str:
        for _ in range(200):
            word = self.rng.choice(NAME_WORDS)
            if entity_type == "public":
                suffix = {"h": "High School", "m": "Middle School"}.get(levels[-1], "Elementary School")
                if "e" in levels and "m" in levels:
                    suffix = "K-8 Center"
            elif entity_type == "charter":
                suffix = self.rng.choice(["Charter Academy", "Charter School", "Preparatory Academy"])
            else:
                suffix = self.rng.choice(["Day School", "Christian Academy", "Montessori School", "Preparatory School"])
            name = f"{word} {suffix}"
            if name not in self.used_names:
                self.used_names.add(name)
                return name
        raise RuntimeError("ran out of names")

    def _tier(self, tier: str, age_days: int, confidence: str = "high", **extra) -> dict:
        generated = self.today - timedelta(days=age_days)
        return {"comparator": "level", "tier": tier, **extra,
                "qualifies": tier in ("good", "small", "very_small", "high", "above_average", "strong"),
                "source_generated_at": generated.strftime("%Y-%m-%dT20:05:00Z"),
                "confidence": confidence}

    def _rating(self, center: int) -> int:
        return max(1, min(10, center + self.rng.randint(-2, 2)))

    # ------------------------------------------------------------ reviews

    def _reviews(self, n: int, pos_share: float, recent_safety_negative: bool = False) -> list[dict]:
        reviews = []
        for i in range(n):
            positive = self.rng.random() < pos_share
            sentiment = "positive" if positive else "negative"
            topics = self.rng.sample(TOPICS, k=self.rng.randint(1, 3))
            if recent_safety_negative and i < 3:
                sentiment, topics = "negative", ["Bullying / Safety", "Teachers / Staff"]
            # Weighted toward recent years, with a tail back to 2011
            age_days = int(self.rng.triangular(10, 15 * 365, 400))
            if recent_safety_negative and i < 3:
                age_days = self.rng.randint(30, 400)
            created = self.today - timedelta(days=age_days, seconds=self.rng.randint(0, 86000))
            body = [self.rng.choice(OPENERS[sentiment])]
            sentiments = []
            for topic in topics:
                body.append(self.rng.choice(SENTENCES[(topic, sentiment)]))
                polarity = self.rng.uniform(0.95, 0.9999) * (1 if positive else -1)
                sentiments.append({"topic": topic, "sentiment_enum": sentiment, "sentiment_polarity": f"{polarity:.4f}"})
            body.append(self.rng.choice(CLOSERS[sentiment]))
            reviews.append({"sentiments": sentiments, "text": " ".join(body), "created_date": self._iso(created),
                            "overall_rating": float(sentiments[0]["sentiment_polarity"])})
        return sorted(reviews, key=lambda r: r["created_date"], reverse=True)

    @staticmethod
    def _sentiment_stats(reviews: list[dict]) -> dict:
        by_topic = {t: {"negative": 0, "total": 0, "neutral": 0, "positive": 0} for t in TOPICS}
        pos = neg = 0
        for review in reviews:
            for s in review["sentiments"]:
                bucket = by_topic[s["topic"]]
                bucket[s["sentiment_enum"]] += 1
                bucket["total"] += 1
                pos += s["sentiment_enum"] == "positive"
                neg += s["sentiment_enum"] == "negative"
        return {"sentiment_by_topic": by_topic, "negative_sentiment_count": neg, "total_reviews": len(reviews),
                "positive_sentiment_count": pos, "total_sentiment_count": pos + neg, "neutral_sentiment_count": 0}

    # ------------------------------------------------------------ one school

    def school(self, spec: dict) -> dict:
        rng = self.rng
        entity_type, levels = spec["entity_type"], spec["levels"]
        city_row = next(c for c in CITIES if c[0] == spec["city"])
        city, county, lat, lon, zip_prefix, district, _ = city_row
        name = spec.get("name") or self._name(entity_type, levels)
        self.used_names.add(name)
        slug = name.lower().replace(" ", "-").replace("'", "")
        school_id = self._new_id()

        doc: dict = {
            "id": f"School fl-{school_id}", "school_id": school_id, "document_type": "School",
            "name": name, "sortable_name": name.lower(), "entity_type": entity_type, "level_codes": levels,
            "city": city, "city_untokenized": city.lower(), "county": county, "state": "FL",
            "zipcode": f"{zip_prefix}{rng.randint(10, 99)}",
            "street": f"{rng.randint(100, 9999)} {rng.choice(STREETS)}",
            "latlon": f"{lat + rng.uniform(-0.04, 0.04):.6f}, {lon + rng.uniform(-0.04, 0.04):.6f}",
            "created": self._iso(self.today - timedelta(days=rng.randint(20, 60))),
            "enrollment": spec.get("enrollment", rng.choice([0, 1]) if rng.random() < 0.08 else rng.randint(180, 1500)),
            "synthetic_generated": True,
        }
        if entity_type != "private":
            doc.update({"school_district_id": district[0], "school_district_name": district[1],
                        "school_district_city": district[2]})

        # Ratings: most public/charter schools have them; private schools rarely do.
        summary = spec.get("summary", "random")
        if summary == "random":
            has = rng.random() < (0.75 if entity_type != "private" else 0.1)
            summary = max(1, min(10, int(rng.gauss(6, 2)))) if has else None
        if summary is not None:
            doc["summary_rating"] = summary
            doc["test_scores_rating"] = self._rating(summary)
            doc["student_progress_rating"] = self._rating(summary)
            doc["low_income_rating"] = self._rating(summary - 1)
            doc["test_scores_rating_hispanic"] = self._rating(summary)
            doc["test_scores_rating_african_american"] = self._rating(summary - 1)
            if rng.random() < 0.6:
                doc["swd_test_scores_rating"] = self._rating(summary - 2)
            if rng.random() < 0.3:
                doc["equity_indicator"] = rng.random() < 0.5

        # Class size and ratio (with the occasional impossible value)
        ratio = spec.get("ratio", rng.choice([118, 43]) if rng.random() < 0.03 else rng.randint(11, 25))
        if spec.get("ratio") or rng.random() < 0.7:
            doc["student_teacher_ratio"] = ratio
            tier = "very_small" if ratio <= 14 else "small" if ratio <= 17 else "average" if ratio <= 21 else "large"
            age = 30 if rng.random() < 0.85 else 700
            doc["class_size"] = self._tier(tier, 110 + age)

        # Attendance
        if rng.random() < 0.7:
            rate = round(rng.uniform(38, 50), 2) if rng.random() < 0.05 else round(rng.uniform(84, 97.5), 2)
            doc["attendance_rate"] = rate
            tier = "good" if rate >= 93 else "concerning" if rate >= 88 else "poor"
            doc["high_attendance"] = self._tier(tier, 110, trend=rng.choice(["improving", "steady", "declining"]))

        ell_tier = spec.get("ell") or (rng.choice(["high", "above_average", "average", "below_average", "low"])
                                        if rng.random() < 0.6 else None)
        if ell_tier:
            doc["ell"] = self._tier(ell_tier, 110, confidence="medium")
        if entity_type != "private" and rng.random() < 0.5:
            doc["gifted_talented"] = rng.random() < 0.45
        if "h" in levels:
            doc["ap_courses"] = rng.sample(AP, k=rng.randint(2, 6))
            doc["college_readiness_rating"] = self._rating(summary or 5)
            doc["graduation_rate"] = round(rng.uniform(78, 97), 1)

        # School-reported profile (osp): about half the schools have one
        if spec.get("profile", rng.random() < 0.55 or "care" in spec):
            doc["osp"] = self._osp(spec, entity_type, slug)
            age = spec.get("profile_age_days", rng.randint(20, 300) if rng.random() < 0.85 else rng.randint(900, 1400))
            doc["osp_as_of"] = (self.today - timedelta(days=age)).strftime("%Y-%m-%d")
            care = spec.get("care", rng.choice(["17:00", "17:30", "18:00", "18:00", "18:30"]) if rng.random() < 0.65 else None)
            if care:
                doc["after_care_end_time"] = care
                doc["after_care_as_of"] = doc["osp_as_of"]
            doc["esp_text"] = [
                f"{name} is a {'tuition-free public charter' if entity_type == 'charter' else entity_type} school "
                f"serving families in {city}.",
                f"The mission of {name} is to help every student grow with confidence.",
            ]

        if entity_type == "private" and (spec.get("tuition") or rng.random() < 0.7):
            doc["tuition"] = spec.get("tuition") or rng.randrange(7000, 24000, 500)

        # Reviews
        n, share = spec.get("reviews") or (0 if rng.random() < 0.25 else rng.randint(1, 18), rng.uniform(0.3, 0.9))
        reviews = self._reviews(n, share, spec.get("recent_safety_negative", False))
        if reviews:
            doc["reviews_full"] = reviews
            doc["reviews_text"] = [r["text"] for r in reviews]
            doc["reviews_positive"] = [r["text"] for r in reviews if r["overall_rating"] > 0][:5]
            doc["reviews_negative"] = [r["text"] for r in reviews if r["overall_rating"] < 0][:5]
        stats = self._sentiment_stats(reviews)
        doc["sentiment_stats"] = stats
        total = stats["total_sentiment_count"]
        doc["avg_review_rating"] = round(1 + 4 * stats["positive_sentiment_count"] / total, 1) if total else 0
        return doc

    def _osp(self, spec: dict, entity_type: str, slug: str) -> dict:
        rng = self.rng
        osp: dict = {"coed": ["coed"], "boarding": ["day"],
                     "school_url": [f"https://www.example.org/{slug}"],
                     "facebook_url": [f"https://www.example.org/{slug}/social"],
                     "dress_code": [rng.choice(["uniform", "dress_code", "no_dress_code"])]}
        start = rng.choice(["7:45 AM", "8:00 AM", "8:15 AM", "8:30 AM"])
        osp["start_time"] = ["8:25 PM"] if rng.random() < 0.02 else [start]
        osp["end_time"] = [rng.choice(["2:45 PM", "3:00 PM", "3:15 PM", "3:30 PM"])]

        bus = spec.get("bus", rng.random() < {"public": 0.8, "charter": 0.5, "private": 0.3}[entity_type])
        osp["transportation"] = ["busses"] if bus else ["none"]

        sub = []
        if spec.get("stem", rng.random() < 0.25):
            sub.append("STEM")
        if entity_type == "private" and rng.random() < 0.3:
            sub.append(rng.choice(["religious", "montessori"]))
        if entity_type == "public" and rng.random() < 0.15:
            sub.append("magnet")
        if sub:
            osp["school_sub_type"] = sub

        clubs = spec.get("clubs") or rng.sample(CLUBS, k=rng.randint(2, 6))
        if spec.get("stem") and "science_club" not in clubs:
            clubs = clubs + ["science_club"]
        osp["student_clubs"] = clubs
        if rng.random() < 0.6:
            osp["arts_visual"] = rng.sample(["drawing", "painting", "ceramics", "photography"], k=rng.randint(1, 3))
        if rng.random() < 0.5:
            osp["arts_music"] = rng.sample(["band", "chorus", "orchestra"], k=rng.randint(1, 2))
        if rng.random() < 0.6:
            sports = rng.sample(SPORTS, k=rng.randint(2, 6))
            osp["boys_sports"], osp["girls_sports"] = sports, sports
        if rng.random() < 0.6 or spec.get("ell") == "high":
            osp["foreign_language"] = ["spanish"]
        osp["family_engagement"] = rng.sample(FAMILY, k=rng.randint(3, 7))
        if rng.random() < 0.6:
            osp["mental_health"] = rng.sample(MENTAL, k=rng.randint(1, 4))
        return osp

    def random_spec(self) -> dict:
        rng = self.rng
        city = rng.choices([c[0] for c in CITIES], weights=[c[6] for c in CITIES])[0]
        entity_type = rng.choices(["public", "charter", "private"], weights=[45, 30, 25])[0]
        levels = rng.choices([["p", "e"], ["e"], ["e", "m"], ["m"], ["h"], ["p", "e", "m"]],
                             weights=[15, 25, 15, 20, 15, 10])[0]
        return {"entity_type": entity_type, "levels": levels, "city": city}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=80, help="total schools to generate, including demo schools")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--today", default="2026-11-03", help="reference date for record ages")
    parser.add_argument("--out", type=Path, default=Path("data/generated/schools_generated.json"))
    args = parser.parse_args()

    gen = Generator(args.seed, datetime.fromisoformat(args.today))
    specs = demo_schools()
    specs += [gen.random_spec() for _ in range(args.count - len(specs))]
    schools = [gen.school(spec) for spec in specs]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(schools, indent=1))
    print(f"Wrote {len(schools)} schools to {args.out}")


if __name__ == "__main__":
    main()
