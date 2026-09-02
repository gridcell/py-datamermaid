"""Reading an image classifier's labels as MERMAID benthic attributes.

Ports the joining half of mermaidr's ``import_coralnet`` and ``import_cpce``
vignettes.  A classifier (CoralNet, ReefCloud, CPCe) labels the points of a
photo quadrat with its own vocabulary;
:func:`datamermaid.get_classification_labelmappings` is the lookup table saying
which MERMAID benthic attribute -- and which growth form, where it matters --
each of those labels stands for.  Join it onto an export and the classifier's
output can be read, and eventually imported, as MERMAID categories.

The export joined here is made up, and built from labels the API itself
returned, so this runs anywhere without a data file to download first.  A real
one is a CSV off the classifier: replace ``classifier_export()`` with
``pandas.read_csv("annotations.csv")`` and the rest of the example is unchanged.

Needs: a network connection.  No MERMAID account -- the label mappings are
public, like the rest of the reference data.

Run it with::

    python examples/11_classification_labelmappings.py
"""

from __future__ import annotations

try:
    import pandas as pd

    import datamermaid
except ImportError as exc:  # explain what to install, instead of a deep traceback
    import sys
    from pathlib import Path

    # `python -P` and PYTHONSAFEPATH=1 keep this directory off sys.path, and the
    # helper below lives in it; without this the handler would fail in its turn.
    sys.path.insert(0, str(Path(__file__).parent))
    from _preflight import missing_dependency

    raise missing_dependency(exc) from None

#: The classifier whose labels are joined below.
PROVIDER = "CoralNet"

#: A label no MERMAID mapping covers, so the unmatched case has something in
#: it.  Every real export has a few: a label the classifier knows and MERMAID
#: does not, and points a human never annotated.
UNKNOWN_LABEL = "Not_A_MERMAID_Label"

#: How many of the provider's labels to build the made-up export from.
SAMPLED_LABELS = 4


def show(frame: pd.DataFrame, *columns: str) -> None:
    """Print the requested columns of ``frame`` that the API actually returned."""
    present = [column for column in columns if column in frame.columns]
    print(frame[present].to_string(index=False))


def classifier_export(labels: list[str]) -> pd.DataFrame:
    """Stand in for a CoralNet annotations export: one row per annotated point.

    The columns are the ones CoralNet writes -- the image name, the point's
    pixel coordinates, and the label assigned to it.  CPCe exports the same
    thing under different headings, which is why the join below is by label
    rather than by position.

    ``labels`` are real provider labels, taken from the mapping table so the
    join has something to match; ``UNKNOWN_LABEL`` is added so it also has
    something not to match.
    """
    points = [*labels, UNKNOWN_LABEL]
    rows = []
    for image in (1, 2):
        for index, label in enumerate(points):
            # Earlier labels get more points than later ones, so the cover
            # computed further down is not a table of ties.
            for point in range(len(points) - index):
                rows.append(
                    {
                        "Name": f"quadrat_{image:02d}.jpg",
                        "Row": 100 * (index + 1),
                        "Column": 100 * (point + 1),
                        "Label": label,
                    }
                )
    return pd.DataFrame(rows)


def with_mermaid_attributes(annotations: pd.DataFrame, mappings: pd.DataFrame) -> pd.DataFrame:
    """Left-join the mappings onto the export, keeping the unmatched rows.

    A left join rather than an inner one: a label MERMAID has no mapping for is
    the thing you most want to see, and an inner join would drop it silently.
    Those rows come back with an empty ``benthic_attribute``.

    The mappings are de-duplicated on the label first.  The join is meant to be
    many rows to one mapping, and a provider that ever listed a label twice
    would otherwise multiply the annotations instead of labelling them.
    """
    lookup = mappings[["provider_label", "benthic_attribute", "growth_form"]].drop_duplicates(
        subset="provider_label"
    )
    return annotations.merge(lookup, how="left", left_on="Label", right_on="provider_label").drop(
        columns="provider_label"
    )


def percent_cover(mapped: pd.DataFrame) -> pd.DataFrame:
    """Points per benthic attribute, per image, as a percentage of that image.

    What a photo-quadrat survey actually reports, and the reason for the join:
    the classifier counts points, MERMAID wants cover by benthic attribute.
    Unmatched points are dropped here rather than counted as cover of nothing.
    """
    counted = (
        mapped.dropna(subset=["benthic_attribute"])
        .groupby(["Name", "benthic_attribute"], as_index=False)
        .size()
        .rename(columns={"size": "points"})
    )
    totals = counted.groupby("Name")["points"].transform("sum")
    counted["percent_cover"] = (100 * counted["points"] / totals).round(1)
    return counted.sort_values(["Name", "percent_cover"], ascending=[True, False])


def main() -> None:
    # The whole table, every provider.  It needs no login, and `limit` caps it
    # like any other getter.
    every = datamermaid.get_classification_labelmappings()
    print(f"{len(every)} label mappings in total, over {every['provider'].nunique()} providers:")
    print(every["provider"].value_counts().to_string())
    print()

    # The providers MERMAID publishes mappings for.  Anything else raises
    # ValueError before a request goes out.
    print("CLASSIFICATION_PROVIDERS:", ", ".join(datamermaid.CLASSIFICATION_PROVIDERS))
    try:
        datamermaid.get_classification_labelmappings("Coralnet")
    except ValueError as exc:
        print("a provider MERMAID does not know ->", exc)
    print()

    # `provider=` filters server-side, so this is the smaller request as well
    # as the smaller frame.
    mappings = datamermaid.get_classification_labelmappings(PROVIDER)
    print(f"{len(mappings)} {PROVIDER} mappings, {mappings.shape[1]} columns:")
    show(mappings.head(8), "provider_label", "benthic_attribute", "growth_form", "provider_id")
    print()

    # `growth_form` is empty where a label maps to an attribute whatever its
    # growth form; the pair (attribute, growth form) is what MERMAID records.
    with_form = mappings["growth_form"].replace("", pd.NA).notna()
    print(f"{int(with_form.sum())} of the {len(mappings)} labels name a growth form as well:")
    show(mappings[with_form].head(5), "provider_label", "benthic_attribute", "growth_form")
    print()

    # == Joining an export ==
    labels = mappings["provider_label"].drop_duplicates().head(SAMPLED_LABELS).tolist()
    annotations = classifier_export(labels)
    print(f"The export: {len(annotations)} annotated points over 2 images")
    show(annotations.head(5), "Name", "Row", "Column", "Label")
    print()

    mapped = with_mermaid_attributes(annotations, mappings)
    print("Joined onto the MERMAID benthic attributes:")
    show(mapped.head(5), "Name", "Label", "benthic_attribute", "growth_form")
    print()

    # The rows worth looking at first: labels the mapping table does not cover.
    # They have to be dealt with -- mapped by hand, or excluded -- before the
    # cover is worth computing, since dropping them changes every percentage.
    unmatched = mapped[mapped["benthic_attribute"].isna()]
    if unmatched.empty:
        print("Every label in the export has a MERMAID mapping.\n")
    else:
        print(f"{len(unmatched)} points carry a label with no MERMAID mapping:")
        print(", ".join(sorted(unmatched["Label"].unique())))
        print()

    print("Percent cover by benthic attribute:")
    print(percent_cover(mapped).to_string(index=False))
    print()

    # The attribute names are MERMAID's own, so they line up with the
    # `benthicattributes` reference table -- which is where to go for the
    # attribute's parent and its place in the hierarchy.
    attributes = datamermaid.get_reference("benthicattributes")
    joined = sorted(mapped["benthic_attribute"].dropna().unique())
    known = attributes[attributes["name"].isin(joined)]
    print(f"{len(known)} of the {len(joined)} joined attributes are in `benthicattributes`:")
    show(known.head(5), "id", "name", "parent", "regions")

    # From here the mapped points would go into a benthic photo quadrat import
    # -- see examples/10_importing_data.py for that half of the workflow, with
    # method="benthicpqt" in place of "fishbelt".


if __name__ == "__main__":
    main()
