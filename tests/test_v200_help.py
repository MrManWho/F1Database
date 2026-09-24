"""v2.0 help: every topic the command palette links to exists on the help page."""

from f1tracker import app as appmod


def test_every_palette_help_link_has_a_section(app, master_client):
    page = master_client.get("/help").get_data(as_text=True)
    missing = [anchor for anchor, _label in appmod.HELP_TOPICS if f'id="{anchor}"' not in page]
    assert missing == []
    for topic in ("team-goals", "announcements", "statistics", "security", "visibility"):
        assert f'href="#{topic}"' in page
