import re

from playwright.sync_api import expect

TITLE_1 = "Graph Neural Networks for Testing"
TITLE_2 = "A Short Note on Mocks"


def search(page, query="graph"):
    page.goto("/")
    page.fill("#q", query)
    page.click("#search-btn")


def open_library(page):
    page.click("#tab-library")


def open_paper(page, title):
    page.locator("#library .item", has_text=title).click()


# ------------------------------------------------------------------ the five user flows
def test_search_shows_result_cards(page):
    search(page)
    expect(page.locator("#status")).to_have_text("2 results for “graph”")
    cards = page.locator("#results .card")
    expect(cards).to_have_count(2)
    first = cards.nth(0)
    expect(first.locator("h3")).to_have_text(TITLE_1)
    expect(first.locator(".meta").first).to_have_text("Ada Lovelace, Alan Turing · 2024")
    link = first.get_by_role("link", name="View on arXiv")
    expect(link).to_have_attribute("href", "http://arxiv.org/abs/2401.00001v1")
    expect(cards.nth(1).locator("h3")).to_have_text(TITLE_2)
    expect(cards.nth(1).locator(".meta").first).to_have_text("Grace Hopper · 2023")


def test_save_adds_paper_to_library(page):
    search(page)
    page.click("#save-0")
    expect(page.locator("#save-msg-0")).to_have_text("Saved.")
    open_library(page)
    expect(page.locator("#lib-status")).to_have_text("1 saved paper")
    item = page.locator("#library .item")
    expect(item).to_have_count(1)
    expect(item.locator(".title")).to_have_text(TITLE_1)
    expect(item.locator(".tag")).to_have_text("arXiv")


def test_saving_same_paper_twice_shows_already_in_library(page):
    search(page)
    page.click("#save-0")
    expect(page.locator("#save-msg-0")).to_have_text("Saved.")
    page.reload()
    search(page)
    page.click("#save-0")
    expect(page.locator("#save-msg-0")).to_contain_text("already in your library")


def test_upload_pdf_adds_paper_with_extracted_title(page, pdf_upload):
    page.goto("/")
    open_library(page)
    page.set_input_files("#pdf-file", pdf_upload)
    page.click("#upload-btn")
    expect(page.locator("#upload-status")).to_have_text("Added: E2E Uploaded Paper Title")
    item = page.locator("#library .item")
    expect(item).to_have_count(1)
    expect(item.locator(".title")).to_have_text("E2E Uploaded Paper Title")
    expect(item.locator(".meta")).to_have_text("Up Loader, Pat Author · 2021")
    expect(item.locator(".tag")).to_have_text("uploaded")


def test_upload_without_choosing_a_file_shows_message(page):
    page.goto("/")
    open_library(page)
    page.click("#upload-btn")
    expect(page.locator("#upload-status")).to_have_text("Choose a PDF first.")


def test_summarize_shows_summary(page, seed_paper):
    seed_paper()
    page.goto("/")
    open_library(page)
    open_paper(page, TITLE_1)
    button = page.locator("#summarize-btn")
    expect(button).to_have_text("Summarize")
    button.click()
    summary = page.locator("#summary")
    expect(summary).to_contain_text("E2E mocked summary problem.")
    expect(summary).to_contain_text("Limitations")
    expect(button).to_have_text("Re-summarize")


def test_ask_shows_answer(page, seed_paper):
    seed_paper()
    page.goto("/")
    open_library(page)
    open_paper(page, TITLE_1)
    page.fill("#question", "What dataset was used?")
    page.click("#ask-btn")
    qa = page.locator("#answers .qa")
    expect(qa).to_have_count(1)
    expect(qa.locator(".q")).to_have_text("What dataset was used?")
    expect(qa.locator(".md")).to_contain_text("E2E mocked answer to: What dataset was used?")
    expect(page.locator("#question")).to_have_value("")  # box cleared after answering


def test_ask_with_blank_question_does_nothing(page, seed_paper):
    seed_paper()
    page.goto("/")
    open_library(page)
    open_paper(page, TITLE_1)
    page.fill("#question", "   ")
    page.click("#ask-btn")
    expect(page.locator("#answers .qa")).to_have_count(0)
    expect(page.locator("#ask-status")).to_have_text("")


# ------------------------------------------------------------------ UI behaviour
def test_summarize_button_label_depends_on_cached_summary(page, seed_paper):
    seed_paper("2401.00001", TITLE_1, summarize=True)   # has a cached summary
    seed_paper("2302.00002", TITLE_2, summarize=False)  # has none
    page.goto("/")
    open_library(page)
    button = page.locator("#summarize-btn")

    open_paper(page, TITLE_1)
    expect(button).to_have_text("Re-summarize")
    expect(page.locator("#summary")).to_contain_text("E2E mocked summary problem.")

    open_paper(page, TITLE_2)
    expect(button).to_have_text("Summarize")
    expect(page.locator("#summary")).to_have_text("")

    open_paper(page, TITLE_1)
    expect(button).to_have_text("Re-summarize")


def test_abstract_show_more_toggle(page):
    search(page)
    long_card, short_card = page.locator("#results .card").nth(0), page.locator("#results .card").nth(1)
    toggle, abstract = long_card.locator(".toggle"), long_card.locator(".abstract")

    expect(toggle).to_be_visible()                      # long abstract overflows the clamp
    expect(toggle).to_have_text("Show more")
    expect(abstract).not_to_have_class(re.compile(r"\bopen\b"))
    clamped_height = abstract.evaluate("e => e.clientHeight")

    toggle.click()
    expect(toggle).to_have_text("Show less")
    expect(abstract).to_have_class(re.compile(r"\bopen\b"))
    assert abstract.evaluate("e => e.clientHeight") > clamped_height  # full text now visible

    toggle.click()
    expect(toggle).to_have_text("Show more")
    expect(abstract).not_to_have_class(re.compile(r"\bopen\b"))

    expect(short_card.locator(".toggle")).to_be_hidden()  # short abstract: no toggle


def test_blank_search_does_nothing_and_does_not_crash(page):
    page.goto("/")
    page.click("#search-btn")                 # empty box
    page.fill("#q", "    ")
    page.click("#search-btn")                 # whitespace only
    page.press("#q", "Enter")
    expect(page.locator("#status")).to_have_text("")
    expect(page.locator("#results .card")).to_have_count(0)
    expect(page.locator("#search-btn")).to_be_enabled()
    # (uncaught JS errors fail the test via the app_page fixture)


def test_enter_key_triggers_search(page):
    page.goto("/")
    page.fill("#q", "graph")
    page.press("#q", "Enter")
    expect(page.locator("#results .card")).to_have_count(2)


def test_empty_library_message_and_tab_switching(page):
    page.goto("/")
    open_library(page)
    expect(page.locator("#lib-status")).to_contain_text("Your library is empty")
    expect(page.locator("#search-view")).to_be_hidden()
    page.click("#tab-search")
    expect(page.locator("#search-view")).to_be_visible()
    expect(page.locator("#library-view")).to_be_hidden()


def test_delete_paper_removes_it_from_library(page, seed_paper):
    seed_paper()
    page.goto("/")
    open_library(page)
    page.once("dialog", lambda d: d.accept())
    page.locator("#library .item .del").click()
    expect(page.locator("#library .item")).to_have_count(0)
    expect(page.locator("#lib-status")).to_contain_text("Your library is empty")
