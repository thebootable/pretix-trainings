Trainings
==========================

.. image:: https://img.shields.io/badge/License-Apache%202.0-blue.svg
   :target: https://opensource.org/licenses/Apache-2.0
   :alt: License: Apache 2.0

This is a plugin for `pretix`_.

Room management, multi-day courses and certificates of attendance for pretix trainings.

The plugin consists of three independently usable modules:

* **Room change** – detects when the room of a date (event or subevent)
  changes, and lets organizers send a notification with preview to all
  affected orders, optionally with an ICS attachment.
* **Sessions** – models multi-day courses as multiple individual dates
  (sessions) within one subevent, including bulk creation, per-session
  check-in lists and an ICS export for attendees.
* **Certificate of attendance** – generates PDF certificates from a layout
  that can be freely designed in the backend, with a configurable issuance
  rule, a sequential certificate number and a ZIP bulk export.

Installation
------------

1. Make sure you have a working pretix installation (>= 2026.7.0), see the
   official `installation guide`_.
2. Activate the virtual environment pretix is installed in.
3. Install this plugin into the same environment, e.g. with::

       pip install -e /path/to/pretix-trainings

   or, once the plugin is published on PyPI, with
   ``pip install pretix-trainings``.
4. Run ``make`` inside this directory to compile the translations (not
   needed if installed via ``pip install`` from an already-built package).
5. Restart pretix (and the worker process, if Celery runs separately).
6. Enable the plugin per organizer/event in the "Plugins" tab of the event
   settings.

Configuration
--------------

All settings live in the event backend under **Settings → Trainings**, and
- for the certificate of attendance - under the separate **Certificate
Layouts** menu item.

Room & room change
^^^^^^^^^^^^^^^^^^^

* **Room meta property name** (``training_room_property``, default
  ``Raum``) – the event/subevent meta data property whose value is
  evaluated as the room. Must exist under "Meta data".
* **Subject / text of the room change email** – with the regular pretix
  placeholders as well as the training-specific placeholders described
  below.
* **Attach calendar file (ICS) to the room change email** – off by
  default, since the ICS attachment conveys the room change unreliably
  depending on the mail client; the binding channel always remains the
  email text itself.

Detected room changes appear under **Open room changes** in the event
menu and must be actively sent with preview, or discarded, from there – no
email is ever sent automatically. This applies both to the room of the
entire date and - for multi-day dates with sessions - to the room of
individual sessions: if only the room of a single day changes, a separate,
independent entry appears for it, identifiable by the affected session.

There is also an event-spanning overview under **Organizer → Open room
changes** (``/control/organizer/<slug>/trainings/room-changes/``): all
open room changes across every event of this organizer that you are
allowed to manage orders for. Preview and sending still happen per event
from there, via the same links as in the event view.

Sessions (multi-day courses)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Sessions are managed directly in a subevent's date editor (its own formset
section) or via **Create multiple dates at once** (bulk creation by
frequency, time and count). Each session can have its own room (otherwise
overriding the subevent's room) as well as its own check-in list.

Certificate of attendance
^^^^^^^^^^^^^^^^^^^^^^^^^^

* **Issuance rule for certificates of attendance**
  (``training_certificate_rule``, default ``checkin_all``):

  - ``always`` – available as soon as the date is over.
  - ``checkin_all`` – check-in on all session check-in lists required
    (without sessions: the date's default check-in list).
  - ``checkin_min`` – check-in on at least N lists, see **Minimum number
    of check-ins**.
  - ``manual`` – approval per order by backend staff.

* **Certificate number format** (``training_certificate_number_format``,
  default ``{event}-{jahr}-{nr:04d}``) – Python format string with the
  placeholders ``{nr}`` (sequential number), ``{event}`` (event slug) and
  ``{jahr}`` (year of issue).
* **Break deduction (minutes per day)**
  (``training_certificate_break_deduction``, default ``0``) – deducted
  from the course hours, once per session day, or once in total without
  sessions.

The PDF layout itself is designed under **Certificate Layouts** with the
familiar pretix editor (freely placeable text fields on a background PDF).
Layouts can be restricted to specific products, or serve as the default
layout for all products not otherwise covered. Available layout
variables: ``attendee_name``, ``course_title``, ``course_dates``,
``course_hours``, ``issue_date`` and ``certificate_number``.

Mail placeholders
^^^^^^^^^^^^^^^^^^

The plugin registers the following placeholders for the order
confirmation, scheduled email rules and bulk mail:

.. list-table::
   :header-rows: 1

   * - Placeholder
     - Content
   * - ``{training_room}``
     - Value of the room meta property (empty if not set)
   * - ``{training_dates}``
     - Date list from the sessions, otherwise the date of the event/subevent
   * - ``{training_certificate_url}``
     - Download link for the certificate of attendance
   * - ``{training_room_old}``
     - Only in the room change email: previous room
   * - ``{training_room_new}``
     - Only in the room change email: new room
   * - ``{training_room_session}``
     - Only in the room change email: "Affects: <session>", if only the
       room of a single session of a multi-day date has changed, empty
       otherwise

**Note for editors of mail templates:** From the moment the
``{training_room}`` placeholder is introduced, no mail template may
hard-code a room anymore. That is the actual purpose of this submodule -
it's the only way to ensure that a later room change actually reaches
everyone, instead of staying stuck as outdated hard-coded text.

Development setup
-----------------

1. Make sure that you have a working `pretix development setup`_.

2. Clone this repository.

3. Activate the virtual environment you use for pretix development.

4. Execute ``python setup.py develop`` within this directory to register this application with pretix's plugin registry.

5. Execute ``make`` within this directory to compile translations.

6. Restart your local pretix server. You can now use the plugin from this repository for your events by enabling it in
   the 'plugins' tab in the settings.

This plugin has CI set up to enforce a few code style rules. To check locally, you need these packages installed::

    pip install flake8 isort black

To check your plugin for rule violations, run::

    black --check .
    isort -c .
    flake8 .

You can auto-fix some of these issues by running::

    isort .
    black .

To automatically check for these issues before you commit, you can run ``.install-hooks``.


License
-------


Copyright 2026 Tobias Berndt

Released under the terms of the Apache License 2.0



.. _pretix: https://github.com/pretix/pretix
.. _pretix development setup: https://docs.pretix.eu/en/latest/development/setup.html
.. _installation guide: https://docs.pretix.eu/en/latest/admin/installation/index.html
