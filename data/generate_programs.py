"""Generate synthetic Miami-area programs (library and community events) in the sample's format.

    python data/generate_programs.py --count 36 --seed 11 --out data/generated/programs_generated.json

All organizations, addresses and events are fictional; records carry "synthetic_generated": true.
Beyond the sample's fields, records carry cost_display ("Free", "$40 per month").
"""

import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from generate import CITIES, STREETS

TZ = "-05:00"  # Miami in November
WEEKDAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

LIBRARIES = {
    "Miami": [("Coral Lantern Branch Library", 25.7725, -80.2150), ("Biscayne Reach Library", 25.7800, -80.1900)],
    "Hialeah": [("Palm Bloom Library", 25.8600, -80.2800)],
    "Coral Gables": [("Banyan Court Library", 25.7200, -80.2700)],
    "Doral": [("Doral Horizon Community Center", 25.8150, -80.3500)],
    "Kendall": [("Sunset Grove Library", 25.6800, -80.3200)],
    "Miami Gardens": [("Gardens Commons Library", 25.9400, -80.2400)],
    "North Miami": [("Northshore Arts Center", 25.8900, -80.1850)],
    "Homestead": [("Redland Fields Library", 25.4700, -80.4750)],
    "Hollywood": [("Seawall Park Library", 26.0100, -80.1500)],
    "Fort Lauderdale": [("Riverwalk Learning Library", 26.1200, -80.1400)],
}

# name, tags, (age_min, age_max), level codes, weekly days, (start, end), cost, blurb
TEMPLATES = [
    ("After-School Homework Help", ["Homework Help", "Tutoring", "After School"], (8, 14), ["e", "m"], ["Mon", "Tue", "Wed", "Thu"], ("15:30", "18:00"), "Free",
     "Volunteer tutors help students with homework and reading after school. Drop in, no registration needed."),
    ("Robotics Club", ["Robotics", "STEM", "After School"], (10, 14), ["m"], ["Tue", "Thu"], ("16:00", "17:30"), "Free",
     "Students build and program robots in teams and prepare for a local robotics challenge."),
    ("Junior Coders", ["Coding", "STEM", "Computers & Technology"], (8, 12), ["e"], ["Sat"], ("10:00", "11:30"), "Free",
     "Kids learn to code games and animations with block-based and beginner text coding."),
    ("Science Saturday", ["Science", "STEM", "Family"], (5, 11), ["e"], ["Sat"], ("11:00", "12:00"), "Free",
     "Hands-on experiments for kids and their grown-ups. Each week explores a new science idea."),
    ("Family Storytime", ["Storytime", "Early Literacy", "Children"], (2, 5), ["p"], ["Wed"], ("10:30", "11:00"), "Free",
     "Stories, songs and rhymes for young children and their caregivers."),
    ("Teen Book Club", ["Book Club", "Teens", "Reading"], (13, 17), ["h"], ["Wed"], ("17:00", "18:00"), "Free",
     "Teens read and talk about a new book each month. Snacks provided."),
    ("Chess Club", ["Chess", "Games", "After School"], (7, 15), ["e", "m"], ["Fri"], ("16:00", "17:30"), "Free",
     "Learn and play chess with coaches. All skill levels welcome."),
    ("Art Studio for Kids", ["Arts & Crafts", "Art", "Children"], (6, 12), ["e"], ["Thu"], ("16:00", "17:00"), "Free",
     "Drawing, painting and clay projects. All materials provided."),
    ("Family English Conversation Night", ["English", "ESL", "Family", "Español"], (0, 99), ["e", "m", "h"], ["Tue"], ("18:00", "19:30"), "Free",
     "Practice everyday English together as a family. Spanish-speaking volunteers can help. Children welcome."),
    ("College Application Workshop", ["College Prep", "Teens", "Workshop"], (15, 18), ["h"], ["Sat"], ("13:00", "15:00"), "Free",
     "Help with college essays, applications and financial aid forms."),
    ("SAT Prep Practice", ["Test Prep", "Teens", "Tutoring"], (15, 18), ["h"], ["Mon", "Wed"], ("17:00", "18:30"), "$40 per month",
     "Practice tests and small-group review for the SAT."),
    ("Youth Soccer Clinic", ["Sports", "Soccer", "After School"], (6, 13), ["e", "m"], ["Mon", "Wed"], ("17:00", "18:30"), "$25 per season",
     "Skills and games with certified coaches at the park next to the center."),
]


class ProgramGenerator:
    def __init__(self, seed: int, today: datetime):
        self.rng = random.Random(seed)
        self.today = today
        self.ids: set[int] = set()

    def _id(self) -> int:
        while True:
            i = self.rng.randint(900000, 999999)
            if i not in self.ids:
                self.ids.add(i)
                return i

    def _instances(self, days: list[str], start: str, end: str, weeks: tuple[int, int], tags: list[str],
                   slug: str) -> list[dict]:
        """Weekly sessions from `weeks[0]` to `weeks[1]` weeks from today (negative = past)."""
        out = []
        week0 = self.today - timedelta(days=self.today.weekday())
        for w in range(weeks[0], weeks[1]):
            for d in days:
                day = week0 + timedelta(weeks=w, days=WEEKDAYS[d])
                status = "past" if day.date() < self.today.date() else "current" if day.date() == self.today.date() else "upcoming"
                iid = self._id()
                out.append({
                    "end_date": day.strftime("%Y-%m-%d"),
                    "start_time": f"2000-01-01T{start}:00{TZ}",
                    "end_time": f"2000-01-01T{end}:00{TZ}",
                    "description": "{'room': \"Meeting Room\"}",
                    "active": True, "id": iid,
                    "url": f"https://www.example.org/{slug}/events/{iid}",
                    "start_date": day.strftime("%Y-%m-%d"), "status": status,
                    "tags": [{"name": t, "id": abs(hash(t)) % 9000} for t in tags],
                })
        return out

    def program(self, city: str, library: tuple, template: tuple, weeks=(-2, 8), zip_override: str | None = None,
                name: str | None = None) -> dict:
        rng = self.rng
        lib_name, lat, lon = library
        t_name, tags, (amin, amax), levels, days, (start, end), cost, blurb = template
        row = next(c for c in CITIES if c[0] == city)
        slug = lib_name.lower().replace(" ", "-")
        pid = self._id()
        instances = self._instances(days, start, end, weeks, tags, slug)
        upcoming = [i for i in instances if i["status"] in ("upcoming", "current")]
        zipcode = zip_override or f"{row[4]}{rng.randint(10, 99)}"
        street = f"{rng.randint(100, 9999)} {rng.choice(STREETS)}"
        created = (self.today - timedelta(days=rng.randint(20, 60))).strftime(f"%Y-%m-%dT%H:%M:%S{TZ}")
        name = name or t_name
        days_text = ", ".join(days)
        return {
            "id": f"Program fl-{pid}", "program_id": pid, "name": name, "source_name": name,
            "description": f"{blurb} Meets {days_text}, {_ampm(start)}-{_ampm(end)}. "
                           f"{'This program is free.' if cost == 'Free' else 'Fee: ' + cost + '.'} "
                           "Please check the event calendar for dates and times.",
            "program_type": "library" if "Library" in lib_name else "community",
            "tag_names": tags, "instances": instances,
            "active_instance_count": len(upcoming), "upcoming_instance_count": len(upcoming),
            "next_start_date": upcoming[0]["start_date"] if upcoming else None,
            "age_min_search": amin, "age_max_search": amax, "all_ages": amin == 0 and amax >= 99,
            "age_display": "All ages" if amin == 0 and amax >= 99 else f"Ages {amin}-{amax}",
            "level_code": levels, "level": "UG",
            "city": city, "county": row[1], "state": "FL", "geo_state": "FL", "FIPScounty": 12086 if "Miami" in row[1] else 12011,
            "zipcode": zipcode, "street": street, "latlon": f"{lat:.6f}, {lon:.6f}", "address_type": "physical",
            "has_available_registration": rng.random() < 0.6,
            "organization_count": 1,
            "organizations": [{"zipcode": zipcode, "home_page_url": f"https://www.example.org/{slug}",
                               "latlon": f"{lat:.6f}, {lon:.6f}", "city": city, "phone": f"(305) 555-0{rng.randint(100, 199)}",
                               "street": street, "organization_id": self._id(), "name": lib_name, "county": row[1],
                               "state": "FL", "source_name": lib_name}],
            "created": created, "modified": created, "view_created": created,
            "cost_display": cost, "synthetic_generated": True,
        }


def _ampm(hhmm: str) -> str:
    h, m = map(int, hhmm.split(":"))
    return f"{(h - 1) % 12 + 1}:{m:02d}{'am' if h < 12 else 'pm'}"


def demo_programs(gen: ProgramGenerator) -> list[dict]:
    """Programs that fill the gaps the demo schools leave (see data/generate.py demo_schools)."""
    coral_lantern = LIBRARIES["Miami"][0]  # about 1 km from Tamarind Cove STEM Academy
    robotics = ("After-School Robotics Club", ["Robotics", "STEM", "After School", "Teens"], (10, 14), ["m"],
                ["Mon", "Tue", "Wed", "Thu"], ("17:00", "18:30"), "Free",
                "Middle schoolers build and program robots in teams. Pickup by 6:30pm. Registration required, limited spots.")
    homework = TEMPLATES[0]
    summer = ("Summer Robotics Camp", ["Robotics", "STEM", "Camp"], (10, 14), ["m"], ["Mon", "Wed", "Fri"],
              ("09:00", "12:00"), "Free", "A summer camp for young engineers.")
    english = TEMPLATES[8]
    return [
        gen.program("Miami", coral_lantern, robotics),
        gen.program("Miami", coral_lantern, homework),
        # Only past sessions: should never be recommended as available
        gen.program("Miami", LIBRARIES["Miami"][1], summer, weeks=(-14, -10)),
        gen.program("Hialeah", LIBRARIES["Hialeah"][0], english),
        # City and ZIP don't match (a Georgia ZIP), like the sample's Derry, NH record
        gen.program("Doral", LIBRARIES["Doral"][0], TEMPLATES[2], zip_override="30306"),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=36)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--today", default="2026-11-03")
    parser.add_argument("--out", type=Path, default=Path("data/generated/programs_generated.json"))
    args = parser.parse_args()

    gen = ProgramGenerator(args.seed, datetime.fromisoformat(args.today))
    programs = demo_programs(gen)
    cities = list(LIBRARIES)
    while len(programs) < args.count:
        city = gen.rng.choice(cities)
        library = gen.rng.choice(LIBRARIES[city])
        template = gen.rng.choice(TEMPLATES)
        weeks = (-4, gen.rng.choice([-1, 6, 8, 10])) if gen.rng.random() < 0.15 else (-2, gen.rng.choice([6, 8, 10]))
        programs.append(gen.program(city, library, template, weeks=weeks))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(programs, indent=1))
    print(f"Wrote {len(programs)} programs to {args.out}")


if __name__ == "__main__":
    main()
