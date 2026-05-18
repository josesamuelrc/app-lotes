import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

# ==========================================
# 1. CONFIGURACIÓN DE LA PÁGINA (Vista Móvil y Desktop)
# ==========================================
st.set_page_config(
    page_title="PBO - Empresas Polar", 
    page_icon="🏢", 
    layout="centered"
)

# --- LOGO OFICIAL ---
logo_url = "https://empresaspolar.com"
try:
    st.image(logo_url, width=280)
except Exception as e:
    st.warning("⚠️ No se pudo cargar el logo en línea.")

st.title("📋 Producto Bajo Observación (PBO)")
st.caption("Sistema interno de control y monitoreo de producto retenido — Empresas Polar")

# ==========================================
# 2. CONEXIÓN Y GESTIÓN DE BASE DE DATOS EN LA NUBE (POSTGRESQL)
# ==========================================
def get_db_connection():
    """Establece conexión con PostgreSQL en la nube usando st.secrets"""
    return psycopg2.connect(
        host=st.secrets["DB_HOST"],
        database=st.secrets["DB_NAME"],
        user=st.secrets["DB_USER"],
        password=st.secrets["DB_PASSWORD"],
        port=st.secrets["DB_PORT"]
    )

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Tabla macro: Lotes bajo observación (Activos)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lotes_db (
            id_pbo TEXT PRIMARY KEY,
            producto TEXT,
            formato TEXT,
            lote TEXT,
            orden TEXT,
            fecha_produccion TEXT,
            defecto_general TEXT,
            cantidad_total_latas INTEGER,
            ubicacion TEXT
        );
    ''')
    
    # Tabla: Paletas iniciales retenidas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS paletas_db (
            id SERIAL PRIMARY KEY,
            id_pbo TEXT REFERENCES lotes_db (id_pbo) ON DELETE CASCADE,
            nro_ticket TEXT UNIQUE,
            camadas_sueltas INTEGER,
            defecto TEXT,
            nca REAL,
            estatus TEXT
        );
    ''')
    
    # Tabla: Nuevas paletas generadas en Reproceso
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reproceso_db (
            id SERIAL PRIMARY KEY,
            id_pbo TEXT REFERENCES lotes_db (id_pbo) ON DELETE CASCADE,
            tickets_originales_consumidos TEXT,
            nuevo_ticket_reprocesado TEXT UNIQUE,
            camadas_sueltas INTEGER,
            estatus_calidad TEXT,
            estatus_logistica TEXT,
            observacion_laboratorio TEXT
        );
    ''')
    
    # Tablas del Archivo Histórico Permanente (Inmutable)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historico_pbo_db (
            id_pbo TEXT PRIMARY KEY,
            producto TEXT,
            lote TEXT,
            fecha_cierre TEXT,
            motivo_cierre TEXT,
            operador_cierre TEXT
        );
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historico_paletas_db (
            id SERIAL PRIMARY KEY,
            id_pbo TEXT,
            nro_ticket TEXT,
            camadas_sueltas INTEGER,
            defecto TEXT,
            nca REAL,
            estatus TEXT
        );
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historico_reproceso_db (
            id SERIAL PRIMARY KEY,
            id_pbo TEXT,
            tickets_originales_consumidos TEXT,
            nuevo_ticket_reprocesado TEXT,
            camadas_sueltas INTEGER,
            estatus_calidad TEXT,
            estatus_logistica TEXT,
            observacion_laboratorio TEXT
        );
    ''')
    
    # Insertar datos de simulación si la base de datos está completamente vacía
    cursor.execute("SELECT COUNT(*) FROM lotes_db")
    if cursor.fetchone()[0] == 0:
        cursor.execute("SELECT COUNT(*) FROM historico_pbo_db")
        if cursor.fetchone()[0] == 0:
            # PBO-001 de ejemplo inicial
            cursor.execute("""
                INSERT INTO lotes_db VALUES ('PBO-001 (Malta Polar)', 'Malta Polar', '12oz Sleek', 'L26135', 'ORD-9921', '2026-05-15', 'Lata Abollada', 4000, 'Almacen de PBO') ON CONFLICT DO NOTHING;
                INSERT INTO paletas_db (id_pbo, nro_ticket, camadas_sueltas, defecto, nca, estatus) VALUES ('PBO-001 (Malta Polar)', 'TK-8812', 0, 'Lata Abollada', 4.5, 'Reprocesado') ON CONFLICT DO NOTHING;
                INSERT INTO reproceso_db (id_pbo, tickets_originales_consumidos, nuevo_ticket_reprocesado, camadas_sueltas, estatus_calidad, estatus_logistica, observacion_laboratorio) VALUES ('PBO-001 (Malta Polar)', 'TK-8812', 'TK-9901 (REP)', 0, 'En Control de Calidad', 'En espera', 'Pendiente por evaluar') ON CONFLICT DO NOTHING;
            """)
            
            # PBO-002 de ejemplo inicial
            cursor.execute("""
                INSERT INTO lotes_db VALUES ('PBO-002 (Polar Light)', 'Polar Light', '8.4 oz', 'L26199', 'ORD-7712', '2026-05-16', 'Litografía Corrida', 2000, 'Transicion') ON CONFLICT DO NOTHING;
                INSERT INTO paletas_db (id_pbo, nro_ticket, camadas_sueltas, defecto, nca, estatus) VALUES ('PBO-002 (Polar Light)', 'TK-5511', 0, 'Litografía Corrida', 1.2, 'Sin reprocesar') ON CONFLICT DO NOTHING;
            """)
            
    conn.commit()
    cursor.close()
    conn.close()

# Inicializar Base de Datos en el arranque seguro en la nube
try:
    init_db()
except Exception as e:
    st.error(f"Error crítico de conexión inicial con Supabase: {e}")

# Listas globales fijas
ESTATUS_OPCIONES = ["Sin reprocesar", "Reprocesado", "Briqueteado", "Aceptado con desviación"]
ESTATUS_DICTAMEN_CALIDAD = ["En Control de Calidad", "Chequeado", "Liberado"]
ESTATUS_DICTAMEN_LOGISTICA = ["En espera", "Confirmado", "Inconsistencia"]
UBICACIONES_LOGISTICA = ["Almacen de PBO", "Transicion", "Almacen de PT"]

# ==========================================
# 3. AUTOMATIZACIÓN DE CIERRE INDUSTRIAL (BACKGROUND TASK)
# ==========================================
def ejecutar_higiene_y_cierre_automatico(usuario_actual):
    conn = get_db_connection()
    # Traer todos los PBOs activos
    df_lotes = pd.read_sql_query("SELECT * FROM lotes_db", conn)
    
    for _, lote in df_lotes.iterrows():
        pbo_id = lote["id_pbo"]
        
        # Consultar estados interconectados usando sintaxis %s compatible con PostgreSQL
        df_orig = pd.read_sql_query("SELECT * FROM paletas_db WHERE id_pbo = %s", conn, params=[pbo_id])
        df_rep = pd.read_sql_query("SELECT * FROM reproceso_db WHERE id_pbo = %s", conn, params=[pbo_id])
        
        condicion_originales = not df_orig.empty and not (df_orig["estatus"] == "Sin reprocesar").any()
        condicion_nuevas = not df_rep.empty and (df_rep["estatus_calidad"] == "Liberado").all() and (df_rep["estatus_logistica"] == "Confirmado").all()
        
        if condicion_originales and condicion_nuevas:
            cursor = conn.cursor()
            try:
                # 1. Mover al histórico macro
                cursor.execute(
                    "INSERT INTO historico_pbo_db VALUES (%s, %s, %s, %s, %s, %s);",
                    (pbo_id, lote["producto"], lote["lote"], datetime.now().strftime("%Y-%m-%d %H:%M"), "Cierre Automático Integral", usuario_actual)
                )
                
                # 2. Copiar paletas iniciales al histórico
                for _, row in df_orig.iterrows():
                    cursor.execute(
                        "INSERT INTO historico_paletas_db (id_pbo, nro_ticket, camadas_sueltas, defecto, nca, estatus) VALUES (%s, %s, %s, %s, %s, %s);",
                        (pbo_id, row["nro_ticket"], row["camadas_sueltas"], row["defecto"], row["nca"], row["estatus"])
                    )
                
                # 3. Copiar reprocesos al histórico
                for _, row in df_rep.iterrows():
                    cursor.execute(
                        "INSERT INTO historico_reproceso_db (id_pbo, tickets_originales_consumidos, nuevo_ticket_reprocesado, camadas_sueltas, estatus_calidad, estatus_logistica, observacion_laboratorio) VALUES (%s, %s, %s, %s, %s, %s, %s);",
                        (pbo_id, row["tickets_originales_consumidos"], row["nuevo_ticket_reprocesado"], row["camadas_sueltas"], row["estatus_calidad"], row["estatus_logistica"], row["observacion_laboratorio"])
                    )
                
                # 4. Eliminar de tablas activas de monitoreo (Higiene de Datos)
                cursor.execute("DELETE FROM lotes_db WHERE id_pbo = %s;", (pbo_id,))
                cursor.execute("DELETE FROM paletas_db WHERE id_pbo = %s;", (pbo_id,))
                cursor.execute("DELETE FROM reproceso_db WHERE id_pbo = %s;", (pbo_id,))
                
                conn.commit()
                st.toast(f"🎉 ¡El caso {pbo_id} cumplió dictámenes y fue archivado exitosamente!")
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Error en cierre automático: {e}")
            finally:
                cursor.close()
                
    conn.close()

# ==========================================
# 4. BARRA LATERAL (CONTROL DE ACCESO Y IDENTIFICACIÓN)
# ==========================================
st.sidebar.header("🔑 Identificación de Usuario")
usuario = st.sidebar.text_input("Nombre del Operador", value="Operador de Turno")
departamento = st.sidebar.selectbox(
    "Selecciona tu Departamento", 
    ["Público / Solo Lectura", "🔬 Calidad", "🛠️ Reproceso / Operaciones", "📦 Logística"]
)
st.sidebar.divider()
st.sidebar.info(f"Conectado como:\n**{usuario}**\nSector: **{departamento}**")

# Ejecutar verificación automática de cierres en cada interacción
try:
    ejecutar_higiene_y_cierre_automatico(usuario)
except:
    pass

# Leer estados actuales desde la Base de Datos en la nube
conn = get_db_connection()
lotes_activos_df = pd.read_sql_query("SELECT * FROM lotes_db", conn)
paletas_activas_df = pd.read_sql_query("SELECT * FROM paletas_db", conn)
reprocesos_activos_df = pd.read_sql_query("SELECT * FROM reproceso_db", conn)
conn.close()

# ==========================================
# 5. PANEL DE CONTROL GENERAL (KPIs INDUSTRIALES)
# ==========================================
st.subheader("📊 Panel de Control PBO Activo")

total_pbos = len(lotes_activos_df)
total_latas_retenidas = lotes_activos_df["cantidad_total_latas"].sum() if not lotes_activos_df.empty else 0
paletas_pendientes = len(paletas_activas_df[paletas_activas_df["estatus"] == "Sin reprocesar"]) if not paletas_activas_df.empty else 0

kpi1, kpi2, kpi3 = st.columns(3)
kpi1.metric("PBOs Activos en Planta", total_pbos)
kpi2.metric("Total Latas Retenidas", f"{total_latas_retenidas:,}")
kpi3.metric("Paletas Sin Reprocesar", paletas_pendientes)

st.divider()
st.write("### 🚨 Lotes bajo Observación en Línea")
st.dataframe(
    lotes_activos_df, 
    column_config={
        "id_pbo": "ID PBO", "producto": "Producto", "formato": "Formato", 
        "lote": "Lote", "orden": "Orden Fabricación", "fecha_produccion": "Fecha Prod.", 
        "defecto_general": "Defecto General", "cantidad_total_latas": "Cantidad (Latas)", 
        "ubicacion": "Ubicación Física"
    },
    use_container_width=True, 
    hide_index=True
)

# ==========================================
# 6. PANEL DINÁMICO POR DEPARTAMENTO (PERMISOS ACCIONES)
# ==========================================
st.divider()
st.subheader("⚡ Acciones Disponibles")

if departamento == "Público / Solo Lectura":
    st.info("Visualización general activa. No tienes permisos para modificar datos.")

elif "Calidad" in departamento:
    st.error("🔒 Permisos de Nivel: CALIDAD")
    accion_calidad = st.radio(
        "¿Qué acción deseas ejecutar?", 
        ["➕ Crear Nuevo PBO", "📦 Añadir Paletas", "🔄 Actualización de Paletas", "🔬 Dictamen de Reproceso", "🗑️ Eliminar PBO"], 
        horizontal=True
    )
    st.divider()

    if lotes_activos_df.empty and accion_calidad != "➕ Crear Nuevo PBO":
        st.warning("No hay casos PBO activos en planta en este momento.")
    else:
        # ACCIÓN: CREAR ENCABEZADO PBO
        if accion_calidad == "➕ Crear Nuevo PBO":
            with st.form("form_crear_pbo", clear_on_submit=True):
                st.write("### Crear Encabezado Macro de PBO")
                prod = st.text_input("Producto (Ej: Malta Polar, Polar Ice, Regional)")
                formato = st.selectbox("Formato de Envase", ["8.4 oz", "12oz Sleek", "355ml Regular"])
                lote_prod = st.text_input("Lote de Producción")
                orden_prod = st.text_input("Orden de Fabricación (SAP)")
                fecha_p = st.date_input("Fecha de Producción", datetime.now())
                defecto_gen = st.text_input("Defecto General Detectado", placeholder="Ej: Falla de Barniz, Litografía Movida...")
                cant_pbo = st.number_input("Cantidad Total de Latas Involucradas", min_value=1, value=1000, step=1)
                
                if st.form_submit_button("Generar PBO en Base de Datos"):
                    if prod and lote_prod and orden_prod and defecto_gen:
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        
                        # Conteo seguro usando cursores de Postgres
                        cursor.execute("SELECT COUNT(*) FROM historico_pbo_db;")
                        total_historicos = cursor.fetchone()[0]
                        cursor.execute("SELECT COUNT(*) FROM lotes_db;")
                        total_activos = cursor.fetchone()[0]
                        nuevo_id_pbo = f"PBO-{total_historicos + total_activos + 1:03d} ({prod})"
                        
                        try:
                            cursor.execute(
                                "INSERT INTO lotes_db VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Almacen de PBO');",
                                (nuevo_id_pbo, prod, formato, lote_prod, orden_prod, str(fecha_p), defecto_gen, cant_pbo)
                            )
                            conn.commit()
                            st.success(f"¡{nuevo_id_pbo} registrado exitosamente en el servidor central!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al guardar en la red: {e}")
                        finally:
                            cursor.close()
                            conn.close()
                    else: 
                        st.error("Por favor completa todos los campos obligatorios del lote.")

        # ACCIÓN: AÑADIR PALETAS / TICKETS A UN PBO
        elif accion_calidad == "📦 Añadir Paletas":
            pbo_seleccionado = st.selectbox("Selecciona el PBO específico", lotes_activos_df["id_pbo"], key="pbo_carga_masiva")
            
            defecto_heredado = lotes_activos_df[lotes_activos_df["id_pbo"] == pbo_seleccionado]["defecto_general"].values[0]
            num_paletas_a_crear = st.number_input("¿Cuántas paletas/tickets vas a registrar en lote?", min_value=1, max_value=20, value=3)
            
            df_plantilla = pd.DataFrame({
                "Nro Ticket": [""] * num_paletas_a_crear,
                "Camadas Sueltas": [0] * num_paletas_a_crear,
                "Defecto Específico": [defecto_heredado] * num_paletas_a_crear, 
                "% NCA": [0.0] * num_paletas_a_crear,
                "Estatus": ["Sin reprocesar"] * num_paletas_a_crear
            })
            
            tabla_ingreso = st.data_editor(
                df_plantilla,
                column_config={
                    "Nro Ticket": st.column_config.TextColumn("Número de Ticket (Único)", required=True),
                    "Camadas Sueltas": st.column_config.NumberColumn("Camadas Sueltas", min_value=0, max_value=50, step=1),
                    "Defecto Específico": st.column_config.TextColumn("Defecto Específico (Modificable)", required=True),
                    "% NCA": st.column_config.NumberColumn("% NCA", min_value=0.0, max_value=100.0, format="%.2f%%"),
                    "Estatus": st.column_config.SelectboxColumn("Estatus Inicial", options=ESTATUS_OPCIONES)
                },
                hide_index=True, use_container_width=True, key=f"editor_masivo_{pbo_seleccionado}"
            )
            
            if st.button("💾 Guardar Bloque de Paletas"):
                if "" in tabla_ingreso["Nro Ticket"].values or "" in tabla_ingreso["Defecto Específico"].values: 
                    st.error("❌ Error: Todas las paletas deben poseer obligatoriamente Número de Ticket y Defecto.")
                else:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    errores = False
                    for _, fila in tabla_ingreso.iterrows():
                        try:
                            cursor.execute(
                                "INSERT INTO paletas_db (id_pbo, nro_ticket, camadas_sueltas, defecto, nca, estatus) VALUES (%s, %s, %s, %s, %s, %s);",
                                (pbo_seleccionado, fila["Nro Ticket"], int(fila["Camadas Sueltas"]), fila["Defecto Específico"], float(fila["% NCA"]), fila["Estatus"])
                            )
                        except psycopg2.IntegrityError:
                            st.error(f"❌ El número de Ticket '{fila['Nro Ticket']}' ya existe en el sistema global en la nube.")
                            errores = True
                            break
                    if not errores:
                        conn.commit()
                        st.success("¡Bloque de paletas guardado con éxito!")
                        st.rerun()
                    cursor.close()
                    conn.close()

        # ACCIÓN: ACTUALIZACIÓN EN LOTE DE PALETAS EXISTENTES
        elif accion_calidad == "🔄 Actualización de Paletas":
            pbo_ver = st.selectbox("1. Filtra por el PBO correspondiente", lotes_activos_df["id_pbo"], key="pbo_modif_masiv")
            df_paletas_pbo = paletas_activas_df[paletas_activas_df["id_pbo"] == pbo_ver] if not paletas_activas_df.empty else pd.DataFrame()
            
            if df_paletas_pbo.empty: 
                st.warning("Este PBO no tiene paletas individuales asignadas en sistema.")
            else:
                tickets_seleccionados = st.multiselect("2. Selecciona los Tickets a actualizar simultáneamente:", options=df_paletas_pbo["nro_ticket"].unique())
                if tickets_seleccionados:
                    with st.form("form_guardado_unico_directo"):
                        mod_estatus = st.selectbox("Cambiar Estatus Operacional a:", ["-- No modificar estatus --"] + ESTATUS_OPCIONES)
                        escribir_nuevo_defecto = st.checkbox("Modificar descripción de defecto de estas paletas")
                        mod_defecto = st.text_input("Nuevo Defecto:", disabled=not escribir_nuevo_defecto)
                        mod_nca = st.number_input("Modificar % NCA (-1 para ignorar):", min_value=-1.0, max_value=100.0, value=-1.0, step=0.1)
                        mod_camadas = st.number_input("Actualizar Nro Camadas (-1 para ignorar):", min_value=-1, max_value=50, value=-1, step=1)
                        
                        if st.form_submit_button("💾 Aplicar Cambios Estructurados"):
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            
                            for tkt in tickets_seleccionados:
                                if mod_estatus != "-- No modificar estatus --":
                                    cursor.execute("UPDATE paletas_db SET estatus = %s WHERE nro_ticket = %s;", (mod_estatus, tkt))
                                if escribir_nuevo_defecto and mod_defecto:
                                    cursor.execute("UPDATE paletas_db SET defecto = %s WHERE nro_ticket = %s;", (mod_defecto, tkt))
                                if mod_nca != -1.0:
                                    cursor.execute("UPDATE paletas_db SET nca = %s WHERE nro_ticket = %s;", (mod_nca, tkt))
                                if mod_camadas != -1:
                                    cursor.execute("UPDATE paletas_db SET camadas_sueltas = %s WHERE nro_ticket = %s;", (mod_camadas, tkt))
                            
                            conn.commit()
                            cursor.close()
                            conn.close()
                            st.success("¡Base de datos centralizada en la nube actualizada!")
                            st.rerun()

        # ACCIÓN: DICTAMEN TÉCNICO DE REPROCESO (LIBERACIÓN FINAL)
        elif accion_calidad == "🔬 Dictamen de Reproceso":
            st.write("### 📝 Dictamen Masivo de Paletas Post-Reproceso (Laboratorio)")
            pbo_evaluar = st.selectbox("1. Selecciona el PBO a dictaminar:", lotes_activos_df["id_pbo"], key="pbo_dict_masivo")
            df_reproceso_pbo = reprocesos_activos_df[reprocesos_activos_df["id_pbo"] == pbo_evaluar] if not reprocesos_activos_df.empty else pd.DataFrame()
            
            if df_reproceso_pbo.empty: 
                st.warning("El PBO seleccionado no cuenta con registros de paletas nuevas provenientes de reproceso.")
            else:
                tickets_evaluar = st.multiselect("2. Selecciona todos los tickets de reproceso a dictaminar:", options=df_reproceso_pbo["nuevo_ticket_reprocesado"].unique())
                if tickets_evaluar:
                    with st.form("form_dictamen_masivo_lab"):
                        nuevo_estatus_rep = st.selectbox("Estatus Dictamen Control de Calidad:", ESTATUS_DICTAMEN_CALIDAD)
                        observacion_lab = st.text_area("Observación Técnica / Justificación de Liberación:")
                        
                        if st.form_submit_button("💾 Estampar Firma y Dictamen Técnico"):
                            if observacion_lab:
                                conn = get_db_connection()
                                cursor = conn.cursor()
                                for tkt in tickets_evaluar:
                                    cursor.execute(
                                        "UPDATE reproceso_db SET estatus_calidad = %s, observacion_laboratorio = %s WHERE nuevo_ticket_reprocesado = %s;",
                                        (nuevo_estatus_rep, f"[{usuario}]: {observacion_lab}", tkt)
                                    )
                                conn.commit()
                                cursor.close()
                                conn.close()
                                st.success(f"¡Dictamen '{nuevo_estatus_rep}' grabado!")
                                st.rerun()
                            else: 
                                st.error("Es obligatorio colocar una justificación técnica o de laboratorio.")

        # ACCIÓN: ELIMINAR O RECHAZAR PBO COMPLETO
        elif accion_calidad == "🗑️ Eliminar PBO":
            pbo_a_borrar = st.selectbox("Selecciona el caso PBO a remover del sistema:", lotes_activos_df["id_pbo"])
            motivo_cancelacion = st.text_input("Escribe el motivo detallado del descarte/eliminación (Obligatorio):")
            
            if st.button("❌ Confirmar Eliminación y Forzar Archivo", type="primary"):
                if motivo_cancelacion:
                    conn = get_db_connection()
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    
                    cursor.execute("SELECT * FROM lotes_db WHERE id_pbo = %s;", (pbo_a_borrar,))
                    lote_data = cursor.fetchone()
                    df_orig_del = pd.read_sql_query("SELECT * FROM paletas_db WHERE id_pbo = %s", conn, params=[pbo_a_borrar])
                    df_rep_del = pd.read_sql_query("SELECT * FROM reproceso_db WHERE id_pbo = %s", conn, params=[pbo_a_borrar])
                    
                    try:
                        cursor.execute(
                            "INSERT INTO historico_pbo_db VALUES (%s, %s, %s, %s, %s, %s);",
                            (pbo_a_borrar, lote_data["producto"], lote_data["lote"], datetime.now().strftime("%Y-%m-%d %H:%M"), f"Cancelado manual por Calidad. Motivo: {motivo_cancelacion}", usuario)
                        )
                        for _, row in df_orig_del.iterrows():
                            cursor.execute("INSERT INTO historico_paletas_db (id_pbo, nro_ticket, camadas_sueltas, defecto, nca, estatus) VALUES (%s, %s, %s, %s, %s, %s);", (pbo_a_borrar, row["nro_ticket"], row["camadas_sueltas"], row["defecto"], row["nca"], row["estatus"]))
                        for _, row in df_rep_del.iterrows():
                            cursor.execute("INSERT INTO historico_reproceso_db (id_pbo, tickets_originales_consumidos, nuevo_ticket_reprocesado, camadas_sueltas, estatus_calidad, estatus_logistica, observacion_laboratorio) VALUES (%s, %s, %s, %s, %s, %s, %s);", (pbo_a_borrar, row["tickets_originales_consumidos"], row["nuevo_ticket_reprocesado"], row["camadas_sueltas"], row["estatus_calidad"], row["estatus_logistica"], row["observacion_laboratorio"]))
                        
                        cursor.execute("DELETE FROM lotes_db WHERE id_pbo = %s;", (pbo_a_borrar,))
                        cursor.execute("DELETE FROM paletas_db WHERE id_pbo = %s;", (pbo_a_borrar,))
                        cursor.execute("DELETE FROM reproceso_db WHERE id_pbo = %s;", (pbo_a_borrar,))
                        
                        conn.commit()
                        st.success("¡Caso removido de planta y bloqueado inmutablemente en el histórico!")
                        st.rerun()
                    except Exception as e:
                        conn.rollback()
                        st.error(f"Error en transacción: {e}")
                    finally:
                        cursor.close()
                        conn.close()
                else: 
                    st.warning("Debes especificar detalladamente el motivo de eliminación reglamentaria.")

elif "Reproceso" in departamento:
    st.warning("🛠️ Permisos de Nivel: REPROCESO / OPERACIONES")
    if lotes_activos_df.empty: 
        st.info("No hay casos PBO abiertos en piso de planta para ejecutar reproceso físico.")
    else:
        pbo_target = st.selectbox("1. Selecciona el caso PBO asignado a tu línea", lotes_activos_df["id_pbo"], key="pbo_target_rep")
        df_originales_pbo = paletas_activas_df[paletas_activas_df["id_pbo"] == pbo_target] if not paletas_activas_df.empty else pd.DataFrame()
        
        if df_originales_pbo.empty: 
            st.warning("Este caso PBO no posee paletas/tickets iniciales cargados por Calidad.")
        else:
            tickets_consumidos = st.multiselect("2. Selecciona las paletas ORIGINALES (bloqueadas) consumidas en el vaciado/reproceso:", options=df_originales_pbo["nro_ticket"].unique())
        
            if tickets_consumidos:
                num_nuevos_tickets = st.number_input("3. ¿Cuántas paletas NUEVAS de Producto Terminado se generaron?", min_value=1, max_value=20, value=2)
                df_plantilla_rep = pd.DataFrame({"Nuevo Ticket Reprocesado": [""] * num_nuevos_tickets, "Camadas Sueltas": [0] * num_nuevos_tickets})
                
                tabla_reproceso = st.data_editor(
                    df_plantilla_rep, 
                    column_config={
                        "Nuevo Ticket Reprocesado": st.column_config.TextColumn("Ticket Nuevo Generado", required=True), 
                        "Camadas Sueltas": st.column_config.NumberColumn("Camadas Restantes", min_value=0, max_value=50, step=1)
                    }, 
                    hide_index=True, use_container_width=True, key=f"editor_reproceso_{pbo_target}"
                )
                
                if st.button("🚀 Registrar Cierre de Línea y Nuevos Tickets"):
                    if "" in tabla_reproceso["Nuevo Ticket Reprocesado"].values: 
                        st.error("Rellena todos los números de ticket generados por la ensacadora/paletizadora.")
                    else:
                        cadena_consumidos = ", ".join(tickets_consumidos)
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        error_save = False
                        
                        try:
                            for _, fila in tabla_reproceso.iterrows():
                                cursor.execute(
                                    "INSERT INTO reproceso_db (id_pbo, tickets_originales_consumidos, nuevo_ticket_reprocesado, camadas_sueltas, estatus_calidad, estatus_logistica, observacion_laboratorio) VALUES (%s, %s, %s, %s, 'En Control de Calidad', 'En espera', 'Pendiente por evaluar');",
                                    (pbo_target,  cadena_consumidos, fila["Nuevo Ticket Reprocesado"], int(fila["Camadas Sueltas"]))
                                )
                            
                            for tkt in tickets_consumidos:
                                cursor.execute("UPDATE paletas_db SET estatus = 'Reprocesado' WHERE nro_ticket = %s;", (tkt,))
                                
                            conn.commit()
                        except psycopg2.IntegrityError:
                            st.error("❌ Conflicto: Uno de los tickets de reproceso introducidos ya existe en el servidor en la nube.")
                            error_save = True
                        finally:
                            cursor.close()
                            conn.close()
                            
                        if not error_save:
                            st.success("¡Lote de reproceso registrado y enviado a cola de inspección de Calidad y Logística!")
                            st.rerun()

elif "Logística" in departamento:
    st.info("📦 Permisos de Nivel: LOGÍSTICA / DICTAMEN DE STOCK")
    if lotes_activos_df.empty: 
        st.info("No hay casos PBO activos en planta para coordinar movimientos físicos.")
    else:
        with st.form("form_unificado_logistica", clear_on_submit=False):
            pbo_log = st.selectbox("1. Selecciona el PBO a gestionar en almacén:", lotes_activos_df["id_pbo"], key="pbo_log_unificado")
            nueva_ubica = st.selectbox("Reubicar lote físico completo (Ubicación SAP / Galpón):", UBICACIONES_LOGISTICA)
            
            df_rep_pbo = reprocesos_activos_df[reprocesos_activos_df["id_pbo"] == pbo_log] if not reprocesos_activos_df.empty else pd.DataFrame()
            
            if df_rep_pbo.empty:
                st.warning("Este caso PBO aún no cuenta con paletas de reproceso fabricadas por Operaciones.")
                tickets_log = []; nuevo_estado_log = "En espera"
            else:
                tickets_log = st.multiselect("Selecciona los tickets nuevos validados en físico (Conteo de Camadas):", options=df_rep_pbo["nuevo_ticket_reprocesado"].unique())
                nuevo_estado_log = st.selectbox("Ajustar Estatus de Verificación Logística:", ESTATUS_DICTAMEN_LOGISTICA)
            
            if st.form_submit_button("💾 Confirmar Movimiento y Conteo Físico"):
                conn = get_db_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute("UPDATE lotes_db SET ubicacion = %s WHERE id_pbo = %s;", (nueva_ubica, pbo_log))
                    for tkt in tickets_log:
                        cursor.execute("UPDATE reproceso_db SET estatus_logistica = %s WHERE nuevo_ticket_reprocesado = %s;", (nuevo_estado_log, tkt))
                    
                    conn.commit()
                    st.success("¡Inventario verificado y ubicación guardada en el servidor central!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
                finally:
                    cursor.close()
                    conn.close()

# ==========================================
# 7. SECCIÓN DE CONSULTA, REPORTES Y TRAZABILIDAD (MÓDULOS DE VISTA)
# ==========================================
st.divider()
st.subheader("🔍 Desglose de Piso y Auditoría")

conn = get_db_connection()
paletas_activas_df = pd.read_sql_query("SELECT * FROM paletas_db", conn)
reprocesos_activos_df = pd.read_sql_query("SELECT * FROM reproceso_db", conn)
historico_pbo_df = pd.read_sql_query("SELECT * FROM historico_pbo_db", conn)
conn.close()

filtro_global = st.selectbox("Filtrar paneles inferiores por caso PBO activo", ["Ver Todo"] + list(lotes_activos_df["id_pbo"]))

display_tab1, display_tab2, display_tab3 = st.tabs(["📋 Paletas Iniciales Retenidas", "🔄 Reprocesos Activos", "🏛️ Archivo de Auditoría Histórica"])

with display_tab1:
    df_f1 = paletas_activas_df if filtro_global == "Ver Todo" else paletas_activas_df[paletas_activas_df["id_pbo"] == filtro_global] if not paletas_activas_df.empty else pd.DataFrame()
    st.dataframe(
        df_f1, 
        column_config={"id_pbo": "ID PBO", "nro_ticket": "Nro Ticket", "camadas_sueltas": "Camadas", "defecto": "Defecto Detallado", "nca": "% NCA", "estatus": "Estatus"},
        use_container_width=True, hide_index=True
    )

with display_tab2:
    if reprocesos_activos_df.empty: 
        st.info("No existen registros de paletas de reproceso activas en este momento.")
    else:
        df_f2 = reprocesos_activos_df if filtro_global == "Ver Todo" else reprocesos_activos_df[reprocesos_activos_df["id_pbo"] == filtro_global]
        st.dataframe(
            df_f2, 
            column_config={"id_pbo": "ID PBO", "tickets_originales_consumidos": "Tickets Origen", "nuevo_ticket_reprocesado": "Ticket Reproceso", "camadas_sueltas": "Camadas", "estatus_calidad": "Dictamen Calidad", "estatus_logistica": "Dictamen Logística", "observacion_laboratorio": "Observaciones Lab."},
            use_container_width=True, hide_index=True
        )

with display_tab3:
    if historico_pbo_df.empty:
        st.info("El archivo histórico centralizado está vacío.")
    else:
        st.success("🏛️ Registro Inmutable de PBOs Liberados y Archivados de Planta:")
        st.dataframe(
            historico_pbo_df, 
            column_config={"id_pbo": "ID PBO", "producto": "Producto", "lote": "Lote", "fecha_cierre": "Fecha Cierre", "motivo_cierre": "Motivo del Cierre", "operador_cierre": "Cerrado Por"},
            use_container_width=True, hide_index=True
        )
        
        st.divider()
        st.write("### 🔍 Consultor de Trazabilidad Retroactiva (Auditorías)")
        pbo_historico_consultar = st.selectbox("Selecciona un PBO cerrado para reconstrucción de lote:", historico_pbo_df["id_pbo"].unique())
        
        if pbo_historico_consultar:
            conn = get_db_connection()
            # Usar cursores de Postgres tipo diccionario para leer la fila
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT * FROM historico_pbo_db WHERE id_pbo = %s;", (pbo_historico_consultar,))
            datos_historicos_macro = cursor.fetchone()
            cursor.close()
            
            df_paletas_historicas = pd.read_sql_query("SELECT * FROM historico_paletas_db WHERE id_pbo = %s", conn, params=[pbo_historico_consultar])
            df_reproceso_historico = pd.read_sql_query("SELECT * FROM historico_reproceso_db WHERE id_pbo = %s", conn, params=[pbo_historico_consultar])
            conn.close()
            
            with st.container(border=True):
                st.write(f"## 📜 REPORTE OFICIAL DE TRAZABILIDAD: {pbo_historico_consultar}")
                st.write(f"🏢 **Planta**: Empresas Polar S.A. | 📅 **Fecha Compilación**: `{datos_historicos_macro['fecha_cierre']}`")
                st.write(f"📦 **Producto**: {datos_historicos_macro['producto']} | 🏷️ **Lote Técnico**: `{datos_historicos_macro['lote']}`")
                st.write(f"👤 **Auditor/Operador Responsable de Firma**: `{datos_historicos_macro['operador_cierre']}`")
                st.write(f"📌 **Dictamen Final de Cierre**: *{datos_historicos_macro['motivo_cierre']}*")
                
                st.write("#### 1. Historial de Tickets Iniciales Retenidos")
                st.dataframe(df_paletas_historicas, use_container_width=True, hide_index=True)
                
                st.write("#### 2. Historial de Disposición, Reproceso y Liberaciones")
                if df_reproceso_historico.empty:
                    st.info("Este lote PBO fue descartado o liberado bajo desviación directamente por Calidad sin pasar por línea de reproceso físico.")
                else:
                    st.dataframe(df_reproceso_historico, use_container_width=True, hide_index=True)
                    
                st.caption("Documento generado por el Sistema de Control de Calidad de Empresas Polar. Copia de respaldo digital inmutable.")