import os
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, html, dcc, dash_table
from dash.dependencies import Input, Output

# ── Rutas de datos ──────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

NOFETAL_PATH   = os.path.join(DATA_DIR, "NoFetal2019.xlsx")
CODIGOS_PATH   = os.path.join(DATA_DIR, "CodigosDeMuerte.xlsx")
DIVIPOLA_PATH  = os.path.join(DATA_DIR, "Divipola.xlsx")

# ── GeoJSON de Colombia por departamento (DANE) ──────────────────────────────
GEOJSON_URL = os.path.join(DATA_DIR, "Colombia.geo.json")

# ── Carga de datos ───────────────────────────────────────────────────────────
def cargar_datos():
    """
    Carga los tres archivos xlsx y devuelve los dataframes.
    Si los archivos no existen genera datos de demostración para que
    la interfaz pueda visualizarse de todas formas.
    """
    archivos_presentes = all(
        os.path.exists(p) for p in [NOFETAL_PATH, CODIGOS_PATH, DIVIPOLA_PATH]
    )

    if archivos_presentes:
        df_muertes  = pd.read_excel(NOFETAL_PATH, dtype={"COD_MUERTE": str})
        df_codigos  = pd.read_excel(CODIGOS_PATH, dtype={"Código de la CIE-10 cuatro caracteres": str})
        df_divipola = pd.read_excel(DIVIPOLA_PATH, dtype={"COD_DANE": str, "COD_MUNICIPIO": str})
        return df_muertes, df_codigos, df_divipola


# ── Preprocesamiento ─────────────────────────────────────────────────────────
def preprocesar(df_muertes, df_codigos, df_divipola):
    """Genera todas las tablas derivadas que necesitan las visualizaciones."""

    # Asegurar tipos
    df_muertes["COD_MUERTE"]      = df_muertes["COD_MUERTE"].astype(str).str.strip().str.upper()
    df_muertes["COD_DEPARTAMENTO"] = pd.to_numeric(df_muertes["COD_DEPARTAMENTO"], errors="coerce")
    df_muertes["MES"]              = pd.to_numeric(df_muertes["MES"], errors="coerce")
    df_muertes["GRUPO_EDAD1"]      = pd.to_numeric(df_muertes["GRUPO_EDAD1"], errors="coerce")
    df_muertes["SEXO"]             = pd.to_numeric(df_muertes["SEXO"], errors="coerce")

    # Nombres de departamentos (desde Divipola)
    dept_nombres = (
        df_divipola[["COD_DEPARTAMENTO", "DEPARTAMENTO"]]
        .drop_duplicates()
        .assign(COD_DEPARTAMENTO=lambda d: pd.to_numeric(d["COD_DEPARTAMENTO"], errors="coerce"))
    )

    # 1. Muertes por departamento
    muertes_depto = (
        df_muertes.groupby("COD_DEPARTAMENTO", as_index=False)
        .size()
        .rename(columns={"size": "TOTAL"})
        .merge(dept_nombres, on="COD_DEPARTAMENTO", how="left")
    )

    # 2. Muertes por mes
    meses_nombres = {
        1:"Ene",2:"Feb",3:"Mar",4:"Abr",5:"May",6:"Jun",
        7:"Jul",8:"Ago",9:"Sep",10:"Oct",11:"Nov",12:"Dic"
    }
    muertes_mes = (
        df_muertes.groupby("MES", as_index=False)
        .size()
        .rename(columns={"size": "TOTAL"})
        .sort_values("MES")
    )
    muertes_mes["MES_NOMBRE"] = muertes_mes["MES"].map(meses_nombres)

    # 3. Ciudades más violentas (homicidios X95*)
    homicidios_mask = df_muertes["COD_MUERTE"].str.startswith("X95")
    df_homicidios   = df_muertes[homicidios_mask].copy()

    # Unimos municipio con Divipola para obtener nombre
    df_div_mun = df_divipola[["COD_DANE", "MUNICIPIO", "DEPARTAMENTO"]].copy()
    df_div_mun["COD_DANE"] = pd.to_numeric(df_div_mun["COD_DANE"], errors="coerce")
    df_muertes["COD_DANE_NUM"] = pd.to_numeric(df_muertes.get("COD_DANE", df_muertes["COD_DEPARTAMENTO"] * 1000 + df_muertes.get("COD_MUNICIPIO", 0)), errors="coerce")

    hom_ciudad = (
        df_homicidios.assign(
            COD_DANE_NUM=lambda d: pd.to_numeric(
                d.get("COD_DANE", d["COD_DEPARTAMENTO"] * 1000 + d.get("COD_MUNICIPIO", 0)),
                errors="coerce"
            )
        )
        .groupby("COD_DANE_NUM", as_index=False)
        .size()
        .rename(columns={"size": "HOMICIDIOS"})
        .merge(df_div_mun, left_on="COD_DANE_NUM", right_on="COD_DANE", how="left")
        .dropna(subset=["MUNICIPIO"])
        .nlargest(5, "HOMICIDIOS")
    )

    # 4. Ciudades con menor mortalidad (top 10 con al menos 10 muertes)
    muertes_ciudad = (
        df_muertes.assign(
            COD_DANE_NUM=lambda d: pd.to_numeric(
                d.get("COD_DANE", d["COD_DEPARTAMENTO"] * 1000 + d.get("COD_MUNICIPIO", 0)),
                errors="coerce"
            )
        )
        .groupby("COD_DANE_NUM", as_index=False)
        .size()
        .rename(columns={"size": "TOTAL"})
        .merge(df_div_mun, left_on="COD_DANE_NUM", right_on="COD_DANE", how="left")
        .dropna(subset=["MUNICIPIO"])
        .query("TOTAL >= 10")
        .nsmallest(10, "TOTAL")
    )

    # 5. Top 10 causas de muerte
    col_cod4  = "Código de la CIE-10 cuatro caracteres"
    col_desc4 = "Descripcion  de códigos mortalidad a cuatro caracteres"
    top_causas = (
        df_muertes.groupby("COD_MUERTE", as_index=False)
        .size()
        .rename(columns={"size": "TOTAL"})
        .merge(df_codigos[[col_cod4, col_desc4]],
               left_on="COD_MUERTE", right_on=col_cod4, how="left")
        .assign(NOMBRE=lambda d: d[col_desc4].fillna("Sin descripción"))
        .nlargest(10, "TOTAL")[["COD_MUERTE", "NOMBRE", "TOTAL"]]
        .rename(columns={"COD_MUERTE": "CÓDIGO", "NOMBRE": "CAUSA"})
    )

    # 6. Muertes por sexo y departamento
    sexo_mapa = {1: "Masculino", 2: "Femenino", 3: "Indeterminado"}
    muertes_sexo_depto = (
        df_muertes.groupby(["COD_DEPARTAMENTO", "SEXO"], as_index=False)
        .size()
        .rename(columns={"size": "TOTAL"})
        .merge(dept_nombres, on="COD_DEPARTAMENTO", how="left")
    )
    muertes_sexo_depto["SEXO_NOMBRE"] = muertes_sexo_depto["SEXO"].map(sexo_mapa).fillna("Otro")

    # 7. Histograma por grupo de edad
    etapas = [
        (range(0,  5),  "Mortalidad neonatal\n< 1 mes"),
        (range(5,  7),  "Mortalidad infantil\n1-11 meses"),
        (range(7,  9),  "Primera infancia\n1-4 años"),
        (range(9,  11), "Niñez\n5-14 años"),
        (range(11, 12), "Adolescencia\n15-19 años"),
        (range(12, 14), "Juventud\n20-29 años"),
        (range(14, 17), "Adultez temprana\n30-44 años"),
        (range(17, 20), "Adultez intermedia\n45-59 años"),
        (range(20, 25), "Vejez\n60-84 años"),
        (range(25, 29), "Longevidad\n85-100+ años"),
        (range(29, 30), "Edad desconocida"),
    ]

    def asignar_etapa(codigo):
        for rango, etapa in etapas:
            if codigo in rango:
                return etapa
        return "Edad desconocida"

    df_edad = df_muertes.dropna(subset=["GRUPO_EDAD1"]).copy()
    df_edad["ETAPA"] = df_edad["GRUPO_EDAD1"].astype(int).map(asignar_etapa)
    orden_etapas = [e for _, e in etapas]
    muertes_edad = (
        df_edad.groupby("ETAPA", as_index=False)
        .size()
        .rename(columns={"size": "TOTAL"})
    )
    muertes_edad["ETAPA"] = pd.Categorical(muertes_edad["ETAPA"], categories=orden_etapas, ordered=True)
    muertes_edad = muertes_edad.sort_values("ETAPA")

    return {
        "muertes_depto":      muertes_depto,
        "muertes_mes":        muertes_mes,
        "hom_ciudad":         hom_ciudad,
        "muertes_ciudad":     muertes_ciudad,
        "top_causas":         top_causas,
        "muertes_sexo_depto": muertes_sexo_depto,
        "muertes_edad":       muertes_edad,
    }


# ── Paleta de colores ────────────────────────────────────────────────────────
COLORES = {
    "fondo":        "#0f1117",
    "superficie":   "#1a1d27",
    "borde":        "#2a2d3e",
    "acento1":      "#e05c5c",
    "acento2":      "#5c9ee0",
    "acento3":      "#5ce0a8",
    "texto":        "#e8e9f0",
    "texto_suave":  "#8b8fa8",
    "gradiente":    ["#5c9ee0", "#e05c5c", "#5ce0a8", "#e0b45c", "#9b5ce0",
                     "#5ce0d4", "#e05ca8", "#a8e05c", "#e0755c", "#5c7ee0"],
}

LAYOUT_BASE = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="'DM Mono', monospace", color=COLORES["texto"], size=11),
    margin=dict(l=40, r=20, t=50, b=40),
    legend=dict(
        bgcolor="rgba(26,29,39,0.8)",
        bordercolor=COLORES["borde"],
        borderwidth=1,
    ),
)


# ── Construcción de figuras ──────────────────────────────────────────────────
def fig_mapa(datos):
    df = datos["muertes_depto"].dropna(subset=["DEPARTAMENTO"])
    import json, urllib.request

    try:
        with urllib.request.urlopen(GEOJSON_URL, timeout=5) as r:
            geojson = json.loads(r.read())

        fig = px.choropleth(
            df,
            geojson=geojson,
            locations="DEPARTAMENTO",
            featureidkey="properties.NOMBRE_DPT",
            color="TOTAL",
            color_continuous_scale=["#1a2a3a", "#5c9ee0", "#e05c5c"],
            labels={"TOTAL": "Muertes"},
            title="Distribución total de muertes por departamento — 2019",
        )
        fig.update_geos(fitbounds="locations", visible=False)
    except Exception:
        # Si no hay acceso al GeoJSON, se muestra un gráfico de barras horizontal como fallback
        df_sorted = df.sort_values("TOTAL", ascending=True)
        fig = px.bar(
            df_sorted,
            x="TOTAL",
            y="DEPARTAMENTO",
            orientation="h",
            color="TOTAL",
            color_continuous_scale=["#1a2a3a", "#5c9ee0", "#e05c5c"],
            labels={"TOTAL": "Muertes", "DEPARTAMENTO": "Departamento"},
            title="Distribución total de muertes por departamento — 2019",
        )

    fig.update_layout(
        **LAYOUT_BASE,
        title_font_size=14,
        coloraxis_colorbar=dict(
            tickfont=dict(color=COLORES["texto"]),
            title=dict(font=dict(color=COLORES["texto"])),
        ),
    )
    return fig


def fig_lineas(datos):
    df = datos["muertes_mes"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["MES_NOMBRE"],
        y=df["TOTAL"],
        mode="lines+markers",
        line=dict(color=COLORES["acento2"], width=2.5),
        marker=dict(size=8, color=COLORES["acento1"],
                    line=dict(color=COLORES["acento2"], width=1.5)),
        fill="tozeroy",
        fillcolor="rgba(92,158,224,0.08)",
        name="Muertes",
        hovertemplate="<b>%{x}</b><br>Muertes: %{y:,}<extra></extra>",
    ))
    fig.update_layout(
        **LAYOUT_BASE,
        title="Total de muertes por mes — Colombia 2019",
        title_font_size=14,
        xaxis=dict(gridcolor=COLORES["borde"], zeroline=False),
        yaxis=dict(gridcolor=COLORES["borde"], zeroline=False),
    )
    return fig


def fig_barras_homicidios(datos):
    df = datos["hom_ciudad"]
    if df.empty:
        fig = go.Figure()
        fig.update_layout(**LAYOUT_BASE, title="Sin datos de homicidios disponibles")
        return fig

    ciudad_label = df["MUNICIPIO"] + ", " + df["DEPARTAMENTO"].fillna("")
    fig = go.Figure(go.Bar(
        x=ciudad_label,
        y=df["HOMICIDIOS"],
        marker=dict(
            color=df["HOMICIDIOS"],
            colorscale=[[0, "#3a1a1a"], [1, COLORES["acento1"]]],
            showscale=False,
            line=dict(color=COLORES["acento1"], width=0.5),
        ),
        text=df["HOMICIDIOS"],
        textposition="outside",
        textfont=dict(color=COLORES["texto"]),
        hovertemplate="<b>%{x}</b><br>Homicidios (X95): %{y:,}<extra></extra>",
    ))
    fig.update_layout(
        **LAYOUT_BASE,
        title="5 ciudades más violentas — Homicidios con arma de fuego (X95) 2019",
        title_font_size=14,
        xaxis=dict(gridcolor=COLORES["borde"]),
        yaxis=dict(gridcolor=COLORES["borde"]),
    )
    return fig


def fig_circular(datos):
    df = datos["muertes_ciudad"]
    if df.empty:
        fig = go.Figure()
        fig.update_layout(**LAYOUT_BASE, title="Sin datos disponibles")
        return fig

    label = df["MUNICIPIO"] + ", " + df["DEPARTAMENTO"].fillna("")
    fig = go.Figure(go.Pie(
        labels=label,
        values=df["TOTAL"],
        hole=0.42,
        marker=dict(
            colors=COLORES["gradiente"][:len(df)],
            line=dict(color=COLORES["fondo"], width=2),
        ),
        textfont=dict(size=10),
        hovertemplate="<b>%{label}</b><br>Muertes: %{value:,}<br>%{percent}<extra></extra>",
    ))
    fig.update_layout(
        **LAYOUT_BASE,
        title="10 ciudades con menor índice de mortalidad — 2019",
        title_font_size=14,
    )
    return fig


def fig_barras_apiladas(datos):
    df = datos["muertes_sexo_depto"].dropna(subset=["DEPARTAMENTO"])
    # Mantener solo Masculino y Femenino para claridad visual
    df = df[df["SEXO_NOMBRE"].isin(["Masculino", "Femenino"])]

    # Ordenar departamentos por total de muertes
    orden = (
        df.groupby("DEPARTAMENTO")["TOTAL"].sum()
        .sort_values(ascending=False).index.tolist()
    )

    colores_sexo = {"Masculino": COLORES["acento2"], "Femenino": COLORES["acento1"]}
    fig = go.Figure()
    for sexo in ["Masculino", "Femenino"]:
        sub = df[df["SEXO_NOMBRE"] == sexo]
        fig.add_trace(go.Bar(
            name=sexo,
            x=sub["DEPARTAMENTO"],
            y=sub["TOTAL"],
            marker_color=colores_sexo[sexo],
            hovertemplate="<b>%{x}</b><br>" + sexo + ": %{y:,}<extra></extra>",
        ))
    fig.update_layout(
        **LAYOUT_BASE,
        barmode="stack",
        title="Muertes por sexo y departamento — Colombia 2019",
        title_font_size=14,
        xaxis=dict(
            categoryorder="array",
            categoryarray=orden,
            tickangle=-45,
            gridcolor=COLORES["borde"],
        ),
        yaxis=dict(gridcolor=COLORES["borde"]),
    )
    return fig


def fig_histograma(datos):
    df = datos["muertes_edad"]
    etiquetas = [str(e).replace("\n", " ") for e in df["ETAPA"]]
    fig = go.Figure(go.Bar(
        x=etiquetas,
        y=df["TOTAL"],
        marker=dict(
            color=df["TOTAL"],
            colorscale=[[0, "#1a2a1a"], [1, COLORES["acento3"]]],
            showscale=False,
            line=dict(color=COLORES["acento3"], width=0.5),
        ),
        text=df["TOTAL"].apply(lambda v: f"{v:,}"),
        textposition="outside",
        textfont=dict(color=COLORES["texto"], size=9),
        hovertemplate="<b>%{x}</b><br>Muertes: %{y:,}<extra></extra>",
    ))
    fig.update_layout(
        **LAYOUT_BASE,
        title="Distribución de muertes por etapa del ciclo de vida — Colombia 2019",
        title_font_size=14,
        xaxis=dict(tickangle=-30, gridcolor=COLORES["borde"]),
        yaxis=dict(gridcolor=COLORES["borde"]),
    )
    return fig


# ── Inicialización ───────────────────────────────────────────────────────────
df_muertes, df_codigos, df_divipola = cargar_datos()
datos = preprocesar(df_muertes, df_codigos, df_divipola)

es_demo = not all(os.path.exists(p) for p in [NOFETAL_PATH, CODIGOS_PATH, DIVIPOLA_PATH])

# ── Layout de la aplicación ──────────────────────────────────────────────────
ESTILOS_TARJETA = {
    "backgroundColor": COLORES["superficie"],
    "border": f"1px solid {COLORES['borde']}",
    "borderRadius": "8px",
    "padding": "20px",
    "marginBottom": "20px",
}

app = Dash(
    __name__,
    title="Mortalidad Colombia 2019",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)

# Expose server for Gunicorn / Render
server = app.server

banner_demo = []
if es_demo:
    banner_demo = [
        html.Div(
            "Modo demostración: los archivos de datos reales no se encontraron en data/. "
            "Los gráficos muestran datos sintéticos con la misma estructura del DANE.",
            style={
                "backgroundColor": "#2a1a00",
                "border": "1px solid #e0b45c",
                "borderRadius": "6px",
                "padding": "12px 20px",
                "marginBottom": "20px",
                "color": "#e0b45c",
                "fontSize": "13px",
            },
        )
    ]

# Tabla de las 10 causas principales
top_causas_df = datos["top_causas"].copy()
top_causas_df["TOTAL"] = top_causas_df["TOTAL"].apply(lambda v: f"{v:,}")

app.layout = html.Div(
    style={"backgroundColor": COLORES["fondo"], "minHeight": "100vh",
           "fontFamily": "'DM Mono', monospace"},
    children=[
        # Fuente
        html.Link(
            rel="stylesheet",
            href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=DM+Sans:wght@300;400;600&display=swap",
        ),

        # Encabezado
        html.Div(
            style={
                "background": f"linear-gradient(135deg, {COLORES['superficie']} 0%, #12151f 100%)",
                "borderBottom": f"1px solid {COLORES['borde']}",
                "padding": "32px 48px 28px",
                "marginBottom": "32px",
            },
            children=[
                html.H1(
                    "Mortalidad en Colombia — 2019",
                    style={"color": COLORES["texto"], "margin": "0 0 6px",
                           "fontFamily": "'DM Sans', sans-serif",
                           "fontWeight": "600", "fontSize": "28px", "letterSpacing": "-0.5px"},
                ),
                html.P(
                    "Análisis exploratorio de datos del DANE · Registros de defunción no fetal\nAndrés Felipe Ricaurte Cortés · Aplicaciones I",
                    style={"color": COLORES["texto_suave"], "margin": "0",
                           "fontSize": "13px", "letterSpacing": "0.3px"},
                ),
            ],
        ),

        # Contenido principal
        html.Div(
            style={"padding": "0 48px 48px"},
            children=[
                *banner_demo,

                # Fila 1 — Mapa y Líneas
                html.Div(
                    style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                           "gap": "20px", "marginBottom": "0"},
                    children=[
                        html.Div(style=ESTILOS_TARJETA, children=[
                            dcc.Graph(id="fig-mapa",
                                      figure=fig_mapa(datos),
                                      config={"displayModeBar": False},
                                      style={"height": "420px"}),
                        ]),
                        html.Div(style=ESTILOS_TARJETA, children=[
                            dcc.Graph(id="fig-lineas",
                                      figure=fig_lineas(datos),
                                      config={"displayModeBar": False},
                                      style={"height": "420px"}),
                        ]),
                    ],
                ),

                # Fila 2 — Barras homicidios y Circular
                html.Div(
                    style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                           "gap": "20px", "marginBottom": "0"},
                    children=[
                        html.Div(style=ESTILOS_TARJETA, children=[
                            dcc.Graph(id="fig-homicidios",
                                      figure=fig_barras_homicidios(datos),
                                      config={"displayModeBar": False},
                                      style={"height": "380px"}),
                        ]),
                        html.Div(style=ESTILOS_TARJETA, children=[
                            dcc.Graph(id="fig-circular",
                                      figure=fig_circular(datos),
                                      config={"displayModeBar": False},
                                      style={"height": "380px"}),
                        ]),
                    ],
                ),

                # Fila 3 — Tabla
                html.Div(
                    style=ESTILOS_TARJETA,
                    children=[
                        html.H3(
                            "10 principales causas de muerte — Colombia 2019",
                            style={"color": COLORES["texto"], "margin": "0 0 16px",
                                   "fontFamily": "'DM Sans', sans-serif",
                                   "fontWeight": "600", "fontSize": "14px"},
                        ),
                        dash_table.DataTable(
                            id="tabla-causas",
                            columns=[
                                {"name": "Código", "id": "CÓDIGO"},
                                {"name": "Causa de muerte", "id": "CAUSA"},
                                {"name": "Total casos", "id": "TOTAL"},
                            ],
                            data=top_causas_df.to_dict("records"),
                            style_table={"overflowX": "auto"},
                            style_header={
                                "backgroundColor": COLORES["borde"],
                                "color": COLORES["texto"],
                                "fontWeight": "500",
                                "border": "none",
                                "fontSize": "12px",
                                "padding": "10px 14px",
                            },
                            style_cell={
                                "backgroundColor": COLORES["superficie"],
                                "color": COLORES["texto"],
                                "border": f"1px solid {COLORES['borde']}",
                                "fontSize": "12px",
                                "padding": "9px 14px",
                                "fontFamily": "'DM Mono', monospace",
                            },
                            style_data_conditional=[
                                {
                                    "if": {"row_index": "odd"},
                                    "backgroundColor": COLORES["fondo"],
                                },
                                {
                                    "if": {"column_id": "CÓDIGO"},
                                    "color": COLORES["acento2"],
                                    "fontWeight": "500",
                                },
                                {
                                    "if": {"column_id": "TOTAL"},
                                    "color": COLORES["acento3"],
                                    "textAlign": "right",
                                },
                            ],
                        ),
                    ],
                ),

                # Fila 4 — Barras apiladas
                html.Div(style=ESTILOS_TARJETA, children=[
                    dcc.Graph(id="fig-sexo-depto",
                              figure=fig_barras_apiladas(datos),
                              config={"displayModeBar": False},
                              style={"height": "440px"}),
                ]),

                # Fila 5 — Histograma
                html.Div(style=ESTILOS_TARJETA, children=[
                    dcc.Graph(id="fig-histograma",
                              figure=fig_histograma(datos),
                              config={"displayModeBar": False},
                              style={"height": "400px"}),
                ]),

                # Pie de página
                html.Div(
                    style={"textAlign": "center", "marginTop": "12px",
                           "color": COLORES["texto_suave"], "fontSize": "11px"},
                    children=[
                        "Fuente: DANE — Estadísticas Vitales Colombia 2019. "
                        "Aplicación desarrollada con Plotly Dash.",
                    ],
                ),
            ],
        ),
    ],
)


# ── Punto de entrada ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
