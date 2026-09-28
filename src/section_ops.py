"""Explicit course section selection for completion grading."""


def list_sections(course):
    sections = list(course.get_sections())
    print("\nSections:")
    for index, section in enumerate(sections, 1):
        print(f"[{index}] {section.name} (Canvas section ID: {section.id})")
    if not sections:
        print("No accessible sections.")
    return sections


def select_section(course, *, section_id=None, all_sections=False, interactive=True):
    if all_sections:
        return None
    if section_id is None and not interactive:
        raise ValueError("Specify --section-id or --all-sections in non-interactive mode")
    sections = list_sections(course)
    if section_id is not None:
        for section in sections:
            if int(section.id) == section_id:
                return section
        raise ValueError(f"Section {section_id} is not accessible in this course")
    if not sections:
        raise ValueError("No accessible sections; cannot choose a grading scope")
    while True:
        try:
            choice = input(f"Select section [1-{len(sections)}] (q to cancel): ").strip()
        except EOFError as exc:
            raise ValueError("No selection received; specify --section-id") from exc
        if choice.lower() == "q":
            raise ValueError("Cancelled; no grades changed")
        if choice.isdigit() and 1 <= int(choice) <= len(sections):
            return sections[int(choice) - 1]
        print("Please enter a section number from the list.")
