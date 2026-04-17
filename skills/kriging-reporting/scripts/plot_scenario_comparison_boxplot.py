# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
Scenario Comparison Box Plot
----------------------------
Builds a box plot comparing estimated values across multiple kriging scenarios.

Usage (agent instructions):
1. Populate `scenario_values` with one key per scenario and a list of numeric estimates.
2. Run the script.
"""

import pandas as pd
import plotly.express as px

# Map each scenario label to a list of estimate values.
scenario_values = {
    "Scenario 1": [],
    "Scenario 2": [],
}

rows = []
for scenario_name, values in scenario_values.items():
    for value in values:
        rows.append({"Scenario": scenario_name, "Estimated Value": value})

df = pd.DataFrame(rows)

fig = px.box(
    df,
    x="Scenario",
    y="Estimated Value",
    title="Kriging Results by Scenario",
)
fig.update_layout(template="plotly_white")
fig.show()
