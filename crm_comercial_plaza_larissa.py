
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "prospectos_plaza_larissa.db"

ETAPAS = [
    "Contacto inicial",
    "Información enviada",
    "Visita programada",
    "Visita realizada",
    "Propuesta enviada",
    "Negociación",
    "Documentación",
    "Contrato",
    "Descartado",
]

GIROS = [
    "Alimentos y bebidas",
    "Salud y farmacia",
    "Belleza y cuidado personal",
    "Servicios",
    "Comercio minorista",
    "Educación",
    "Fitness y bienestar",
    "Entretenimiento",
    "Financiero",
    "Otro",
]

ORIGENES = [
    "Recomendación",
    "Llamada",
    "WhatsApp",
    "Correo",
    "Redes sociales",
    "Visita a la plaza",
    "Corredor inmobiliario",
    "Otro",
]

PRIORIDADES = ["Alta", "Media", "Baja"]


def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS prospectos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            negocio TEXT NOT NULL,
            contacto TEXT,
            telefono TEXT,
            correo TEXT,
            giro TEXT,
            origen TEXT,
            etapa TEXT NOT NULL,
            prioridad TEXT,
            locales_interes TEXT,
            superficie_requerida REAL DEFAULT 0,
            renta_ofrecida REAL DEFAULT 0,
            probabilidad INTEGER DEFAULT 10,
            fecha_contacto TEXT,
            proximo_seguimiento TEXT,
            responsable TEXT,
            comentarios TEXT,
            fecha_creacion TEXT NOT NULL,
            fecha_actualizacion TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS seguimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prospecto_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            tipo TEXT,
            detalle TEXT NOT NULL,
            siguiente_accion TEXT,
            siguiente_fecha TEXT,
            FOREIGN KEY(prospecto_id) REFERENCES prospectos(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS locales (
            local TEXT PRIMARY KEY,
            planta TEXT,
            superficie_m2 REAL,
            estatus TEXT DEFAULT 'Disponible',
            prospecto_asignado INTEGER,
            FOREIGN KEY(prospecto_asignado) REFERENCES prospectos(id)
        )
        """
    )

    locales_existentes = cursor.execute("SELECT COUNT(*) FROM locales").fetchone()[0]
    if locales_existentes == 0:
        locales_base = []
        for i in range(1, 15):
            planta = "PB" if i <= 14 else "PA"
            locales_base.append((f"Local {i:02d}", planta, 0.0, "Disponible", None))
        cursor.executemany(
            """
            INSERT INTO locales
            (local, planta, superficie_m2, estatus, prospecto_asignado)
            VALUES (?, ?, ?, ?, ?)
            """,
            locales_base,
        )

    conn.commit()
    conn.close()


def query_df(query, params=()):
    conn = get_connection()
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def execute(query, params=()):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def money(value):
    return f"${value:,.0f}"


def parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def load_prospectos():
    return query_df("SELECT * FROM prospectos ORDER BY fecha_actualizacion DESC")


def prospecto_label(row):
    return f"#{row['id']} · {row['negocio']}"


st.set_page_config(
    page_title="CRM Comercial — Plaza Larissa",
    page_icon="🏬",
    layout="wide",
)

init_db()

st.title("🏬 CRM comercial — Plaza Larissa")
st.caption("Prospectos, negociaciones, seguimientos y asignación preliminar de los 14 locales.")

pagina = st.sidebar.radio(
    "Sección",
    ["Resumen", "Prospectos", "Seguimientos", "Locales", "Exportar"],
)

prospectos = load_prospectos()
hoy = date.today()

if pagina == "Resumen":
    activos = prospectos[~prospectos["etapa"].isin(["Contrato", "Descartado"])] if not prospectos.empty else prospectos
    contratos = prospectos[prospectos["etapa"] == "Contrato"] if not prospectos.empty else prospectos
    negociacion = prospectos[prospectos["etapa"].isin(["Propuesta enviada", "Negociación", "Documentación"])] if not prospectos.empty else prospectos

    vencidos = 0
    proximos_7 = 0
    if not prospectos.empty:
        fechas = pd.to_datetime(prospectos["proximo_seguimiento"], errors="coerce").dt.date
        vencidos = int(((fechas < hoy) & prospectos["etapa"].isin([e for e in ETAPAS if e not in ["Contrato", "Descartado"]])).sum())
        proximos_7 = int(((fechas >= hoy) & (fechas <= hoy + timedelta(days=7))).sum())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Prospectos activos", len(activos))
    c2.metric("En negociación", len(negociacion))
    c3.metric("Contratos", len(contratos))
    c4.metric("Seguimientos vencidos", vencidos)
    c5.metric("Próximos 7 días", proximos_7)

    if prospectos.empty:
        st.info("Todavía no hay prospectos. Ve a **Prospectos** para registrar el primero.")
    else:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Embudo comercial")
            embudo = (
                prospectos.groupby("etapa", dropna=False)
                .size()
                .reindex(ETAPAS, fill_value=0)
                .reset_index(name="Prospectos")
            )
            st.bar_chart(embudo.set_index("etapa"))

        with col2:
            st.subheader("Valor mensual ponderado")
            activos_valor = prospectos[~prospectos["etapa"].isin(["Descartado"])]
            renta_total = activos_valor["renta_ofrecida"].fillna(0).sum()
            renta_ponderada = (
                activos_valor["renta_ofrecida"].fillna(0)
                * activos_valor["probabilidad"].fillna(0)
                / 100
            ).sum()
            st.metric("Renta mensual ofrecida", money(renta_total))
            st.metric("Renta mensual ponderada", money(renta_ponderada))
            st.caption("Valor ponderado = renta ofrecida × probabilidad de cierre.")

        st.subheader("Seguimientos prioritarios")
        vista = prospectos.copy()
        vista["proximo_seguimiento"] = pd.to_datetime(vista["proximo_seguimiento"], errors="coerce")
        vista = vista[
            (~vista["etapa"].isin(["Contrato", "Descartado"]))
            & vista["proximo_seguimiento"].notna()
        ].sort_values(["proximo_seguimiento", "prioridad"])

        columnas = [
            "id", "negocio", "contacto", "telefono", "etapa",
            "prioridad", "proximo_seguimiento", "responsable"
        ]
        st.dataframe(vista[columnas].head(20), use_container_width=True, hide_index=True)

elif pagina == "Prospectos":
    tab1, tab2 = st.tabs(["Listado y edición", "Nuevo prospecto"])

    with tab2:
        st.subheader("Registrar prospecto")
        with st.form("nuevo_prospecto", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            negocio = c1.text_input("Negocio o marca *")
            contacto = c2.text_input("Persona de contacto")
            telefono = c3.text_input("Teléfono")

            c1, c2, c3 = st.columns(3)
            correo = c1.text_input("Correo")
            giro = c2.selectbox("Giro", GIROS)
            origen = c3.selectbox("Origen", ORIGENES)

            c1, c2, c3 = st.columns(3)
            etapa = c1.selectbox("Etapa", ETAPAS, index=0)
            prioridad = c2.selectbox("Prioridad", PRIORIDADES, index=1)
            responsable = c3.text_input("Responsable", value="Yani")

            c1, c2, c3 = st.columns(3)
            locales_interes = c1.text_input("Locales de interés", placeholder="Ej. 01, 02 y 03")
            superficie = c2.number_input("Superficie requerida (m²)", min_value=0.0, step=5.0)
            renta = c3.number_input("Renta mensual ofrecida", min_value=0.0, step=1000.0)

            c1, c2, c3 = st.columns(3)
            probabilidad = c1.slider("Probabilidad de cierre (%)", 0, 100, 10, 5)
            fecha_contacto = c2.date_input("Fecha de contacto", value=hoy)
            proximo = c3.date_input("Próximo seguimiento", value=hoy + timedelta(days=7))

            comentarios = st.text_area("Comentarios")
            guardar = st.form_submit_button("Guardar prospecto", type="primary")

            if guardar:
                if not negocio.strip():
                    st.error("El nombre del negocio es obligatorio.")
                else:
                    ahora = datetime.now().isoformat(timespec="seconds")
                    execute(
                        """
                        INSERT INTO prospectos (
                            negocio, contacto, telefono, correo, giro, origen,
                            etapa, prioridad, locales_interes, superficie_requerida,
                            renta_ofrecida, probabilidad, fecha_contacto,
                            proximo_seguimiento, responsable, comentarios,
                            fecha_creacion, fecha_actualizacion
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            negocio.strip(), contacto.strip(), telefono.strip(),
                            correo.strip(), giro, origen, etapa, prioridad,
                            locales_interes.strip(), superficie, renta, probabilidad,
                            fecha_contacto.isoformat(), proximo.isoformat(),
                            responsable.strip(), comentarios.strip(), ahora, ahora
                        ),
                    )
                    st.success("Prospecto guardado.")
                    st.rerun()

    with tab1:
        if prospectos.empty:
            st.info("No hay prospectos registrados.")
        else:
            c1, c2, c3, c4 = st.columns(4)
            filtro_etapa = c1.multiselect("Etapa", ETAPAS)
            filtro_giro = c2.multiselect("Giro", sorted(prospectos["giro"].dropna().unique()))
            filtro_prioridad = c3.multiselect("Prioridad", PRIORIDADES)
            busqueda = c4.text_input("Buscar negocio o contacto")

            vista = prospectos.copy()
            if filtro_etapa:
                vista = vista[vista["etapa"].isin(filtro_etapa)]
            if filtro_giro:
                vista = vista[vista["giro"].isin(filtro_giro)]
            if filtro_prioridad:
                vista = vista[vista["prioridad"].isin(filtro_prioridad)]
            if busqueda:
                texto = (
                    vista["negocio"].fillna("")
                    + " "
                    + vista["contacto"].fillna("")
                    + " "
                    + vista["telefono"].fillna("")
                ).str.lower()
                vista = vista[texto.str.contains(busqueda.lower(), regex=False)]

            st.dataframe(
                vista[
                    [
                        "id", "negocio", "contacto", "telefono", "giro", "etapa",
                        "prioridad", "locales_interes", "renta_ofrecida",
                        "probabilidad", "proximo_seguimiento", "responsable"
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

            opciones = {
                prospecto_label(row): int(row["id"])
                for _, row in prospectos.iterrows()
            }
            seleccion = st.selectbox("Editar prospecto", list(opciones.keys()))
            prospecto_id = opciones[seleccion]
            registro = prospectos[prospectos["id"] == prospecto_id].iloc[0]

            with st.expander("Abrir ficha y editar", expanded=True):
                with st.form("editar_prospecto"):
                    c1, c2, c3 = st.columns(3)
                    negocio = c1.text_input("Negocio o marca", value=registro["negocio"] or "")
                    contacto = c2.text_input("Contacto", value=registro["contacto"] or "")
                    telefono = c3.text_input("Teléfono", value=registro["telefono"] or "")

                    c1, c2, c3 = st.columns(3)
                    correo = c1.text_input("Correo", value=registro["correo"] or "")
                    giro_index = GIROS.index(registro["giro"]) if registro["giro"] in GIROS else 0
                    giro = c2.selectbox("Giro", GIROS, index=giro_index)
                    origen_index = ORIGENES.index(registro["origen"]) if registro["origen"] in ORIGENES else 0
                    origen = c3.selectbox("Origen", ORIGENES, index=origen_index)

                    c1, c2, c3 = st.columns(3)
                    etapa = c1.selectbox("Etapa", ETAPAS, index=ETAPAS.index(registro["etapa"]))
                    prioridad = c2.selectbox(
                        "Prioridad", PRIORIDADES,
                        index=PRIORIDADES.index(registro["prioridad"]) if registro["prioridad"] in PRIORIDADES else 1
                    )
                    responsable = c3.text_input("Responsable", value=registro["responsable"] or "")

                    c1, c2, c3 = st.columns(3)
                    locales_interes = c1.text_input(
                        "Locales de interés", value=registro["locales_interes"] or ""
                    )
                    superficie = c2.number_input(
                        "Superficie requerida (m²)",
                        min_value=0.0,
                        value=float(registro["superficie_requerida"] or 0),
                        step=5.0,
                    )
                    renta = c3.number_input(
                        "Renta mensual ofrecida",
                        min_value=0.0,
                        value=float(registro["renta_ofrecida"] or 0),
                        step=1000.0,
                    )

                    c1, c2 = st.columns(2)
                    probabilidad = c1.slider(
                        "Probabilidad de cierre (%)",
                        0, 100, int(registro["probabilidad"] or 0), 5
                    )
                    fecha_base = parse_date(registro["proximo_seguimiento"]) or hoy
                    proximo = c2.date_input("Próximo seguimiento", value=fecha_base)

                    comentarios = st.text_area("Comentarios", value=registro["comentarios"] or "")

                    guardar_cambios = st.form_submit_button("Guardar cambios", type="primary")
                    if guardar_cambios:
                        execute(
                            """
                            UPDATE prospectos SET
                                negocio=?, contacto=?, telefono=?, correo=?, giro=?,
                                origen=?, etapa=?, prioridad=?, locales_interes=?,
                                superficie_requerida=?, renta_ofrecida=?, probabilidad=?,
                                proximo_seguimiento=?, responsable=?, comentarios=?,
                                fecha_actualizacion=?
                            WHERE id=?
                            """,
                            (
                                negocio.strip(), contacto.strip(), telefono.strip(),
                                correo.strip(), giro, origen, etapa, prioridad,
                                locales_interes.strip(), superficie, renta, probabilidad,
                                proximo.isoformat(), responsable.strip(),
                                comentarios.strip(),
                                datetime.now().isoformat(timespec="seconds"),
                                prospecto_id,
                            ),
                        )
                        st.success("Cambios guardados.")
                        st.rerun()

                if st.button("Eliminar prospecto", type="secondary"):
                    execute("DELETE FROM seguimientos WHERE prospecto_id=?", (prospecto_id,))
                    execute("UPDATE locales SET prospecto_asignado=NULL, estatus='Disponible' WHERE prospecto_asignado=?", (prospecto_id,))
                    execute("DELETE FROM prospectos WHERE id=?", (prospecto_id,))
                    st.success("Prospecto eliminado.")
                    st.rerun()

elif pagina == "Seguimientos":
    if prospectos.empty:
        st.info("Primero registra un prospecto.")
    else:
        opciones = {
            prospecto_label(row): int(row["id"])
            for _, row in prospectos.iterrows()
        }
        seleccion = st.selectbox("Prospecto", list(opciones.keys()))
        prospecto_id = opciones[seleccion]

        with st.form("nuevo_seguimiento", clear_on_submit=True):
            c1, c2 = st.columns(2)
            fecha_seg = c1.date_input("Fecha", value=hoy)
            tipo = c2.selectbox(
                "Tipo",
                ["Llamada", "WhatsApp", "Correo", "Reunión", "Visita", "Propuesta", "Otro"],
            )
            detalle = st.text_area("Detalle del seguimiento *")
            siguiente_accion = st.text_input("Siguiente acción")
            siguiente_fecha = st.date_input(
                "Fecha de la siguiente acción", value=hoy + timedelta(days=7)
            )
            guardar = st.form_submit_button("Registrar seguimiento", type="primary")

            if guardar:
                if not detalle.strip():
                    st.error("Escribe el detalle del seguimiento.")
                else:
                    execute(
                        """
                        INSERT INTO seguimientos (
                            prospecto_id, fecha, tipo, detalle,
                            siguiente_accion, siguiente_fecha
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            prospecto_id, fecha_seg.isoformat(), tipo,
                            detalle.strip(), siguiente_accion.strip(),
                            siguiente_fecha.isoformat(),
                        ),
                    )
                    execute(
                        """
                        UPDATE prospectos
                        SET proximo_seguimiento=?, fecha_actualizacion=?
                        WHERE id=?
                        """,
                        (
                            siguiente_fecha.isoformat(),
                            datetime.now().isoformat(timespec="seconds"),
                            prospecto_id,
                        ),
                    )
                    st.success("Seguimiento registrado.")
                    st.rerun()

        historial = query_df(
            """
            SELECT fecha, tipo, detalle, siguiente_accion, siguiente_fecha
            FROM seguimientos
            WHERE prospecto_id=?
            ORDER BY fecha DESC, id DESC
            """,
            (prospecto_id,),
        )
        st.subheader("Historial")
        if historial.empty:
            st.caption("Sin seguimientos registrados.")
        else:
            st.dataframe(historial, use_container_width=True, hide_index=True)

elif pagina == "Locales":
    locales = query_df(
        """
        SELECT
            l.local, l.planta, l.superficie_m2, l.estatus,
            l.prospecto_asignado, p.negocio
        FROM locales l
        LEFT JOIN prospectos p ON p.id = l.prospecto_asignado
        ORDER BY l.local
        """
    )

    st.subheader("Inventario comercial")
    st.caption("Puedes corregir las superficies cuando tengas el cuadro definitivo de áreas.")

    editados = st.data_editor(
        locales[["local", "planta", "superficie_m2", "estatus"]],
        use_container_width=True,
        hide_index=True,
        disabled=["local"],
        column_config={
            "estatus": st.column_config.SelectboxColumn(
                "Estatus",
                options=["Disponible", "Apartado", "En negociación", "Contratado"],
            ),
            "superficie_m2": st.column_config.NumberColumn(
                "Superficie (m²)", min_value=0.0, step=1.0
            ),
        },
        key="editor_locales",
    )

    if st.button("Guardar inventario"):
        for _, row in editados.iterrows():
            execute(
                """
                UPDATE locales
                SET planta=?, superficie_m2=?, estatus=?
                WHERE local=?
                """,
                (row["planta"], row["superficie_m2"], row["estatus"], row["local"]),
            )
        st.success("Inventario actualizado.")
        st.rerun()

    st.divider()
    st.subheader("Asignar prospecto a un local")

    if prospectos.empty:
        st.info("No hay prospectos disponibles para asignar.")
    else:
        c1, c2, c3 = st.columns(3)
        local_sel = c1.selectbox("Local", locales["local"].tolist())
        prospecto_opciones = {"Sin asignar": None}
        prospecto_opciones.update({
            prospecto_label(row): int(row["id"])
            for _, row in prospectos.iterrows()
        })
        prospecto_sel = c2.selectbox("Prospecto", list(prospecto_opciones.keys()))
        estatus_sel = c3.selectbox(
            "Estatus resultante",
            ["Disponible", "Apartado", "En negociación", "Contratado"],
            index=2,
        )

        if st.button("Guardar asignación", type="primary"):
            execute(
                """
                UPDATE locales
                SET prospecto_asignado=?, estatus=?
                WHERE local=?
                """,
                (prospecto_opciones[prospecto_sel], estatus_sel, local_sel),
            )
            st.success("Asignación actualizada.")
            st.rerun()

    st.subheader("Vista de asignaciones")
    st.dataframe(
        locales[["local", "planta", "superficie_m2", "estatus", "negocio"]],
        use_container_width=True,
        hide_index=True,
    )

elif pagina == "Exportar":
    st.subheader("Exportar información")

    seguimientos = query_df(
        """
        SELECT
            s.id, s.prospecto_id, p.negocio, s.fecha, s.tipo,
            s.detalle, s.siguiente_accion, s.siguiente_fecha
        FROM seguimientos s
        LEFT JOIN prospectos p ON p.id = s.prospecto_id
        ORDER BY s.fecha DESC
        """
    )
    locales = query_df(
        """
        SELECT
            l.local, l.planta, l.superficie_m2, l.estatus,
            l.prospecto_asignado, p.negocio
        FROM locales l
        LEFT JOIN prospectos p ON p.id = l.prospecto_asignado
        ORDER BY l.local
        """
    )

    st.download_button(
        "Descargar prospectos CSV",
        data=prospectos.to_csv(index=False).encode("utf-8-sig"),
        file_name="prospectos_plaza_larissa.csv",
        mime="text/csv",
    )
    st.download_button(
        "Descargar seguimientos CSV",
        data=seguimientos.to_csv(index=False).encode("utf-8-sig"),
        file_name="seguimientos_plaza_larissa.csv",
        mime="text/csv",
    )
    st.download_button(
        "Descargar locales CSV",
        data=locales.to_csv(index=False).encode("utf-8-sig"),
        file_name="locales_plaza_larissa.csv",
        mime="text/csv",
    )

    st.warning(
        "La base de datos se guarda en el archivo "
        "`prospectos_plaza_larissa.db`. En Streamlit Community Cloud, "
        "el almacenamiento local puede reiniciarse al volver a desplegar. "
        "Para uso permanente conviene conectar después Google Sheets, "
        "Supabase o una base de datos externa."
    )
