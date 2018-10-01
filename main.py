#!/usr/bin/env python

import os
import re
import urllib
import urllib.request
import sqlite3
from bs4 import BeautifulSoup

# Template for HTML pages
HTML_TEMPLATE = """
    <!DOCTYPE html>
    <html lang="en">
        <head>
            <title>%s</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <link href="main.css" rel="stylesheet">
        </head>
        <body>
            %s
        </body>
    </html>
"""

RESOURCES_PATH = "./pyside2.docset/Contents/Resources"
DOC_PATH = "%s/Documents" % RESOURCES_PATH

# Create the sqlite3 database
DATABASE_CONNECTION = sqlite3.connect("%s/docSet.dsidx" % RESOURCES_PATH)
DATABASE_CURSOR = DATABASE_CONNECTION.cursor()


def init_database():
    """
    Init the database by creating the table and
    dropping it when starting the script.

    Returns the current cursor.
    """
    # Drop the database
    DATABASE_CURSOR.execute('DROP TABLE IF EXISTS searchIndex;')

    # Create the table and its index
    DATABASE_CURSOR.execute('CREATE TABLE searchIndex(id INTEGER PRIMARY KEY, name TEXT, type TEXT, path TEXT);')
    DATABASE_CURSOR.execute('CREATE UNIQUE INDEX anchor ON searchIndex (name, type, path);')


def insert_entry(name: str, entry_type: str, path: str):
    """
    Insert the entry in database.
    """
    DATABASE_CURSOR.execute("INSERT OR IGNORE INTO searchIndex(name, type, path) VALUES (?, ?, ?)", (name, entry_type, path))
    DATABASE_CONNECTION.commit()


def clean_links(body, current_url: str):
    """
    Clean links or remove the ones not related to the documentation.
    """
    for tag in body.find_all(["a", "area"], href=re.compile("^../")):
        if "PySide2" in os.path.abspath("%s/%s" % (os.path.dirname(current_url), tag["href"])):
            tag["href"] = tag["href"].split("/")[-1]
        else:
            # Remove link not related to the documentation
            tag.replaceWithChildren()


def do_request(url: str):
    """
    Do a request to the website.
    Returns a BeautifulSoup4 object if the website is OK.
    Returns None in case of error (404, 500).
    """
    try:
        html: str = urllib.request.urlopen(url).read()

        return BeautifulSoup(html, "html.parser")
    except urllib.error.HTTPError:
        return None


def save_page(file_name: str, title: str, html: str, show_exists_error: bool = True):
    """
    Save a page locally.
    """
    # Write a message if the page already exists
    if show_exists_error and os.path.exists("%s/%s" % (DOC_PATH, file_name)):
        print("\x1b[0;31m%s - %s\x1b[0m" % (file_name, "This page already exists..."))

    with open("%s/%s" % (DOC_PATH, file_name), "w") as file:
        file.write(HTML_TEMPLATE % (title, html))


def download_file(url: str, file_name: str):
    """
    Download a file from the website and save it locally.
    """
    try:
        content: str = urllib.request.urlopen(url).read()

        with open("%s/%s" % (DOC_PATH, file_name), "wb") as file:
            file.write(content)

        return True
    except urllib.error.HTTPError:
        return False


def download_css():
    # Download the CSS file
    download_file("https://doc-snapshots.qt.io/style/pyside.css", "main.css")

    # Get the CSS content
    with open("%s/main.css" % DOC_PATH, "r") as file:
        css_content = file.read()

    # Remove all font-family rules
    css_content = re.sub("(.*)font-family:(.*);?\n", "", css_content)

    # Inject the font rule to the CSS
    css_content = css_content + """
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
        }
    """

    with open("%s/main.css" % DOC_PATH, "w") as file:
        file.write(css_content)


def parse_main_page():
    """
    Parse the main page.
    """
    document: BeautifulSoup = do_request("https://doc-snapshots.qt.io/qtforpython/")

    # Find the body
    body = document.find("div", class_="bodywrapper")

    # Remove the bottom part of the body
    qt_modules = body.find(id="qt-modules")
    qt_modules.findChildren("p")[0].extract()
    qt_modules.findChildren("div")[0].extract()

    # Remove PySide2 from the path
    html_body = str(body).replace('href="PySide2/', 'href="')

    # Update the href with the offline doc links
    html_body = html_body.replace("/index.html", "-index.html")

    # Save the page
    save_page("index.html", str(document.title.string), html_body)

    return body.find_all("a", class_="external")


def parse_module_index_page(module: str):
    """
    Parse the module index page and parse all functions page.
    """
    print("Indexing %s" % module)

    url = "https://doc-snapshots.qt.io/qtforpython/PySide2/%s/index.html" % module

    document: BeautifulSoup = do_request(url)

    if document is None:
        return False

    # Find the body
    body = document.find("div", class_="bodywrapper")

    # Remove useless code
    body.find("div", class_="hide docutils container").extract()

    # Clean links
    clean_links(body, url)

    file_path = "%s-index.html" % module

    # Save the page
    save_page(file_path, str(document.title.string), str(body))

    # Add entry in database
    insert_entry(module, "Module", file_path)

    return body


def parse_class_page(module: str, class_name: str):
    """
    Parse the class page.
    """
    url = "https://doc-snapshots.qt.io/qtforpython/PySide2/%s/%s.html" % (module, class_name)

    document: BeautifulSoup = do_request(url)

    # Find the body
    body = document.find("div", class_="bodywrapper")

    # Remove the anchors from inheritance links
    inherited_strong = body.find("strong", text="Inherited by:")

    if inherited_strong is not None:
        links = inherited_strong.find_next_siblings("a")

        for link in links:
            link["href"] = link["href"].split("#")[0]

    # Clean links
    clean_links(body, url)

    # Download images
    images = body.find_all("img")

    if images is not None:
        for image in images:
            img_src = image["src"].replace('../../', '')
            image_file_name = os.path.basename(img_src)

            # Download the image
            success = download_file("https://doc-snapshots.qt.io/qtforpython/%s" % img_src, image_file_name)

            if success:
                # Change the image src attribute with the new file name
                image["src"] = image_file_name
            else:
                image.extract()

    file_path = "%s.html" % class_name

    # Save the page
    save_page(file_path, str(document.title.string), str(body))

    # Add the class entry in database depending of the type
    database_type = "Class"

    if class_name.endswith("Event"):
        database_type = "Event"
    elif class_name.endswith("Interface"):
        database_type = "Interface"
    elif class_name.endswith("Enum"):
        database_type = "Enum"

    entry_name = "PySide2.%s.%s" % (module, class_name)
    insert_entry(entry_name, database_type, file_path)

    # Find all methods, if there are methods, and insert
    # entries in the database
    synopsis = body.find(id="synopsis")

    # Check if the page have methods to index
    if synopsis is not None:
        # Find all methods and index them
        methods = synopsis.find_all("a", class_="reference internal")

        for method in methods:
            entry_name = "PySide2.%s.%s.%s" % (module, class_name, method.string)
            insert_entry(entry_name, "Method", "%s%s" % (file_path, method["href"]))


def main():
    modules_in_404 = []

    # Create the documents directory
    if not os.path.exists(DOC_PATH):
        os.makedirs(DOC_PATH)

    init_database()
    download_css()
    download_file("https://doc-snapshots.qt.io/style/list_arrow.png", "list_arrow.png")

    modules = parse_main_page()

    for module in modules:
        module_slug = module.string.replace(' ', '')
        module_index_body = parse_module_index_page(module_slug)

        # Some pages are for now in 404. We don't index them
        if module_index_body is False:
            modules_in_404.append(module_slug)
            print("\x1b[0;31m  -- %s\x1b[0m" % "Page not found. Skip...")
            continue

        # Find all functions in the page
        functions = module_index_body\
            .find("div", class_="pysidetoc docutils container")\
            .find_all("a", class_="internal")

        for index, function in enumerate(functions, 1):
            print("  -- %(nb)d functions founds. Indexing %(current)d / %(nb)d" % {'nb': len(functions), 'current': index}, end="\r")
            parse_class_page(module_slug, function.string)

        print("")

    # Remove the links in the main page for modules documentations
    # not found or not available yet
    with open("%s/index.html" % DOC_PATH, "r") as file:
        main_page_body = BeautifulSoup(file.read(), "html.parser")

    for module_in_404 in modules_in_404:
        main_page_body.find("a", href=re.compile(module_in_404)).replaceWithChildren()

    save_page("index.html", str(main_page_body.title.string), str(main_page_body), False)

    # A small copyright :)
    print("")
    print("\x1b[0;32m------------------------------------")
    print("| Developed By Yohan T.            |")
    print("| Find Me On Github:               |")
    print("| https://github.com/Cronos87      |")
    print("------------------------------------\x1b[0m")

if __name__ == '__main__':
    main()
