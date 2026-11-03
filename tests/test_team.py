"""The owner's team (assistant-moderation-v1)."""

from kb import settings_store, team


def test_team_default_and_matching(conn):
    assert settings_store.load(conn).team == team.DEFAULT
    assert team.same_person("Bogdan Stetsenko", "Bogdan Stecenko")
    assert team.same_person("Anastasiya Tarasova", "Anastasia Tarasova")
    assert team.same_person("Galyna Tkachenko", "", "g.tkachenko@adducates.com")
    assert team.same_person("Galyna Tkachenko", "Halyna Tkachenko")
    assert team.same_person("Kate Oleksyuk", "Oleksyuk K.")
    assert not team.same_person("Kate Oleksyuk", "Katya Yaremenko")
    assert not team.same_person("Anastasiya Tarasova", "Anastasiia Zakharuk")
    members = {
        "12": {"username": "Bogdan Stecenko", "email": "b@x"},
        "13": {"username": "Katya Yaremenko", "email": "k@x"},
        "14": {"username": "Kate Oleksyuk", "email": "kate@x"},
    }
    assert team.clickup_members(conn, members) == {"12": "Bogdan Stetsenko", "14": "Kate Oleksyuk"}
    settings_store.save(conn, {"team": ["Katya Yaremenko"]})
    assert team.clickup_members(conn, members) == {"13": "Katya Yaremenko"}


def test_mentions_of_owner_or_team(conn):
    assert team.mentions(conn, "@Roman @Bogdan\nToday: orders", ["Roman Zhukovsky"])
    assert team.mentions(conn, "@Kate please check", ["Roman Zhukovsky"])
    assert not team.mentions(conn, "@Nikita @Olha\nToday: shipment", ["Roman Zhukovsky"])
    assert not team.mentions(conn, "Bogdan was on the call", ["Roman Zhukovsky"])  # no @


def test_saving_other_settings_keeps_the_team(conn, pg_url, config):
    from tests.test_email_drafts import web_client

    client = web_client(conn, pg_url, config)
    h = {"X-KB-Request": "1"}
    r = client.put("/api/settings", json={"app": {"team": ["Kate Oleksyuk"]}}, headers=h)
    assert r.json()["app"]["team"] == ["Kate Oleksyuk"]
    client.put("/api/settings", json={"app": {"reply_drafts_per_day": 3}}, headers=h)
    assert settings_store.load(conn).team == ["Kate Oleksyuk"]
    assert settings_store.load(conn).reply_drafts_per_day == 3
