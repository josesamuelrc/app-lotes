import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

# ==========================================
# 1. CONFIGURACIÓN DE LA PÁGINA 
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
    pass

st.title("📋 Producto Bajo Observación (PBO)")
st.caption("Sistema interno de control y monitoreo de producto retenido — Empresas Polar")

# ==========================================
# 2. CONEXIÓN Y GESTIÓN DE BASE DE DATOS
# ==========================================
def get_db_connection():
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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lotes_db (
            id_pbo TEXT PRIMARY KEY, producto TEXT, formato TEXT, lote TEXT, orden TEXT,
            fecha_produccion TEXT, defecto_general TEXT, cantidad_total_latas INTEGER, ubicacion TEXT
        );
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS paletas_db (
            id SERIAL PRIMARY KEY, id_pbo TEXT REFERENCES lotes_db (id_pbo) ON DELETE CASCADE,
            nro_ticket TEXT UNIQUE, camadas_sueltas INTEGER, defecto TEXT, nca REAL, estatus TEXT
        );
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reproceso_db (
            id SERIAL PRIMARY KEY, id_pbo TEXT REFERENCES lotes_db (id_pbo) ON DELETE CASCADE,
            tickets_originales_consumidos TEXT, nuevo_ticket_reprocesado TEXT UNIQUE,
            camadas_sueltas INTEGER, estatus_calidad TEXT, estatus_logistica TEXT, observacion_laboratorio TEXT
        );
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historico_pbo_db (
            id_pbo TEXT PRIMARY KEY, producto TEXT, lote TEXT, fecha_cierre TEXT, motivo_cierre TEXT, operador_cierre TEXT
        );
    ''')
    cursor.execute('CREATE TABLE IF NOT EXISTS historico_paletas_db (id SERIAL PRIMARY KEY, id_pbo TEXT, nro_ticket TEXT, camadas_sueltas INTEGER, defecto TEXT, nca REAL, estatus TEXT);')
    cursor.execute('CREATE TABLE IF NOT EXISTS historico_reproceso_db (id SERIAL PRIMARY KEY, id_pbo TEXT, tickets_originales_consumidos TEXT, nuevo_ticket_reprocesado TEXT, camadas_sueltas INTEGER, estatus_calidad TEXT, estatus_logistica TEXT, observacion_laboratorio TEXT);')
    conn.commit()
    cursor.close()
    conn.close()

try:
    init_db()
except Exception as e:
    st.error(f"Error de conexión inicial: {e}")

# --- 🚀 ARQUITECTURA DE DATOS ULTRA-VELOZ EN MEMORIA LOCAL ---
def cargar_datos_desde_servidor():
    """Descarga de red masiva (solo ocurre una vez al abrir la app)"""
    conn = get_db_connection()
    st.session_state["lotes_df"] = pd.read_sql_query("SELECT * FROM lotes_db", conn)
    st.session_state["paletas_df"] = pd.read_sql_query("SELECT * FROM paletas_db", conn)
    st.session_state["reprocesos_df"] = pd.read_sql_query("SELECT * FROM reproceso_db", conn)
    st.session_state["historico_pbo_df"] = pd.read_sql_query("SELECT * FROM historico_pbo_db", conn)
    conn.close()

# Inicialización única del estado de la sesión
if "lotes_df" not in st.session_state:
    with st.spinner("Estableciendo enlace de alta velocidad con el servidor..."):
        cargar_datos_desde_servidor()

# Asignación de variables de trabajo directo apuntando a la RAM
lotes_activos_df = st.session_state["lotes_df"]
paletas_activas_df = st.session_state["paletas_df"]
reprocesos_activos_df = st.session_state["reprocesos_df"]
historico_pbo_df = st.session_state["historico_pbo_df"]

# Listas globales de configuración fija
ESTATUS_OPCIONES = ["Sin reprocesar", "Reprocesado", "Briqueteado", "Aceptado con desviación"]
ESTATUS_DICTAMEN_CALIDAD = ["En Control de Calidad", "Chequeado", "Liberado"]
ESTATUS_DICTAMEN_LOGISTICA = ["En espera", "Confirmado", "Inconsistencia"]
UBICACIONES_LOGISTICA = ["Almacen de PBO", "Transicion", "Almacen de PT"]

# ==========================================
# 3. AUTOMATIZACIÓN DE CIERRE INDUSTRIAL
# ==========================================
def ejecutar_higiene_y_cierre_automatico(usuario_actual):
    if lotes_activos_df.empty:
        return
        
    conn = get_db_connection()
    hubo_cierres = False
    
    for _, lote in lotes_activos_df.iterrows():
        pbo_id = lote["id_pbo"]
        
        df_orig = paletas_activas_df[paletas_activas_df["id_pbo"] == pbo_id]
        df_rep = reprocesos_activos_df[reprocesos_activos_df["id_pbo"] == pbo_id]
        
        condicion_originales = not df_orig.empty and not (df_orig["estatus"] == "Sin reprocesar").any()
        condicion_nuevas = not df_rep.empty and (df_rep["estatus_calidad"] == "Liberado").all() and (df_rep["estatus_logistica"] == "Confirmado").all()
        
        if condicion_originales and condicion_nuevas:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO historico_pbo_db VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING;",
                    (pbo_id, lote["producto"], lote["lote"], datetime.now().strftime("%Y-%m-%d %H:%M"), "Cierre Automático Integral", usuario_actual)
                )
                for _, row in df_orig.iterrows():
                    cursor.execute("INSERT INTO historico_paletas_db (id_pbo, nro_ticket, camadas_sueltas, defecto, nca, estatus) VALUES (%s, %s, %s, %s, %s, %s);", (pbo_id, row["nro_ticket"], row["camadas_sueltas"], row["defecto"], row["nca"], row["estatus"]))
                for _, row in df_rep.iterrows():
                    cursor.execute("INSERT INTO historico_reproceso_db (id_pbo, tickets_originales_consumidos, nuevo_ticket_reprocesado, camadas_sueltas, estatus_calidad, estatus_logistica, observacion_laboratorio) VALUES (%s, %s, %s, %s, %s, %s, %s);", (pbo_id, row["tickets_originales_consumidos"], row["nuevo_ticket_reprocesado"], row["camadas_sueltas"], row["estatus_calidad"], row["estatus_logistica"], row["observacion_laboratorio"]))
                
                cursor.execute("DELETE FROM lotes_db WHERE id_pbo = %s;", (pbo_id,))
                cursor.execute("DELETE FROM paletas_db WHERE id_pbo = %s;", (pbo_id,))
                cursor.execute("DELETE FROM reproceso_db WHERE id_pbo = %s;", (pbo_id,))
                conn.commit()
                
                # Sincronización instantánea RAM
                st.session_state["lotes_df"] = st.session_state["lotes_df"][st.session_state["lotes_df"]["id_pbo"] != pbo_id]
                st.session_state["paletas_df"] = st.session_state["paletas_df"][st.session_state["paletas_df"]["id_pbo"] != pbo_id]
                st.session_state["reprocesos_df"] = st.session_state["reprocesos_df"][st.session_state["reprocesos_df"]["id_pbo"] != pbo_id]
                
                nueva_fila_hist = pd.DataFrame([{
                    "id_pbo": pbo_id, "producto": lote["producto"], "lote": lote["lote"],
                    "fecha_cierre": datetime.now().strftime("%Y-%m-%d %H:%M"), "motivo_cierre": "Cierre Automático Integral", "operador_cierre": usuario_actual
                }])
                st.session_state["historico_pbo_df"] = pd.concat([st.session_state["historico_pbo_df"], nueva_fila_hist], ignore_index=True)
                hubo_cierres = True
            except Exception as e:
                conn.rollback()
            finally:
                cursor.close()
    conn.close()
    if hubo_cierres:
        st.rerun()

# ==========================================
# 4. BARRA LATERAL (CONTROLES)
# ==========================================
st.sidebar.header("🔑 Identificación de Usuario")
usuario = st.sidebar.text_input("Nombre del Operador", value="Operador de Turno")
departamento = st.sidebar.selectbox("Selecciona tu Departamento", ["Público / Solo Lectura", "🔬 Calidad", "🛠️ Reproceso / Operaciones", "📦 Logística"])

st.sidebar.divider()
if st.sidebar.button("🔄 Sincronizar Base de Datos (Nube)"):
    cargar_datos_desde_servidor()
    st.sidebar.success("¡Datos actualizados!")
    st.rerun()

try:
    ejecutar_higiene_y_cierre_automatico(usuario)
except:
    pass

# ==========================================
# 5. PANEL DE CONTROL GENERAL (KPIs)
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
st.dataframe(lotes_activos_df, use_container_width=True, hide_index=True)

# ==========================================
# 6. PANEL DINÁMICO POR DEPARTAMENTO
# ==========================================
st.divider()
st.subheader("⚡ Acciones Disponibles")

if departamento == "Público / Solo Lectura":
    st.info("Visualización general activa. No tienes permisos para modificar datos.")

elif "Calidad" in departamento:
    st.error("🔒 Permisos de Nivel: CALIDAD")
    accion_calidad = st.radio("¿Qué acción deseas ejecutar?", ["➕ Crear Nuevo PBO", "🔄 Actualización de Paletas", "🔬 Dictamen de Reproceso", "🗑️ Eliminar PBO"], horizontal=True)
    st.divider()

    if lotes_activos_df.empty and accion_calidad != "➕ Crear Nuevo PBO":
        st.warning("No hay casos PBO activos en planta en este momento.")
    else:
        if accion_calidad == "➕ Crear Nuevo PBO":
            st.write("### Crear Encabezado Macro y Unidades de PBO")
            prod = st.text_input("Producto (Ej: Malta Polar)")
            formato = st.selectbox("Formato de Envase", ["8.4 oz", "12 oz Sleek"])
            lote_prod = st.text_input("Lote de Producción")
            orden_prod = st.text_input("Orden de Fabricación (SAP)")
            fecha_p = st.date_input("Fecha de Producción", datetime.now())
            defecto_gen = st.text_input("Defecto General Detectado")
            
            st.write("#### 📦 Desglose de Unidades Retenidas")
            col1, col2 = st.columns(2)
            cant_paletas = col1.number_input("Cantidad de Paletas Retenidas", min_value=0, value=1, step=1)
            cant_camadas = col2.number_input("Cantidad de Camadas Retenidas", min_value=0, value=0, step=1)
            
            # --- 🔢 CÁLCULO DE CAPACIDAD AUTOMÁTICO ---
            latas_por_paleta = 9912 if formato == "8.4 oz" else 7752
            total_latas = (cant_paletas * latas_por_paleta) + (cant_camadas * 472)
            
            st.info(f"🔢 **Cantidad Total de Latas Calculada:** {total_latas:,} latas (Paletas: {cant_paletas} x {latas_por_paleta} | Camadas: {cant_camadas} x 472)")
            
            # --- 📋 GENERACIÓN AUTOMÁTICA DE FILAS ---
            tipos_lista = ["Paleta"] * cant_paletas + ["Camada"] * cant_camadas
            df_plantilla = pd.DataFrame({
                "Tipo": tipos_lista,
                "Nro Ticket": [""] * len(tipos_lista),
                "Defecto Específico": [defecto_gen] * len(tipos_lista),
                "% NCA": [0.0] * len(tipos_lista),
                "Estatus": ["Sin reprocesar"] * len(tipos_lista)
            })
            
            st.write("📝 **Asigne los números de Ticket respectivos para cada unidad:**")
            tabla_ingreso = st.data_editor(df_plantilla, hide_index=True, use_container_width=True, disabled=["Tipo", "Defecto Específico", "Estatus"])
            
            if st.button("💾 Guardar PBO Completo e Inyectar en Red"):
                if not prod or not lote_prod or not orden_prod or not defecto_gen:
                    st.error("Error: Llene todos los campos del encabezado macro.")
                elif "" in tabla_ingreso["Nro Ticket"].values:
                    st.error("Error: Todos los campos 'Nro Ticket' en la tabla deben estar llenos.")
                else:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM historico_pbo_db;")
                    total_historicos = cursor.fetchone()[0]
                    total_activos = len(lotes_activos_df)
                    nuevo_id_pbo = f"PBO-{total_historicos + total_activos + 1:03d} ({prod})"
                    
                    try:
                        # Guardar PBO macro
                        cursor.execute("INSERT INTO lotes_db VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Almacen de PBO');", (nuevo_id_pbo, prod, formato, lote_prod, orden_prod, str(fecha_p), defecto_gen, int(total_latas)))
                        
                        # Inyectar unidades asociadas
                        nuevas_paletas_lista = []
                        for _, fila in tabla_ingreso.iterrows():
                            n_camadas = 0 if fila["Tipo"] == "Paleta" else 1
                            cursor.execute("INSERT INTO paletas_db (id_pbo, nro_ticket, camadas_sueltas, defecto, nca, estatus) VALUES (%s, %s, %s, %s, %s, %s);", (nuevo_id_pbo, fila["Nro Ticket"], n_camadas, fila["Defecto Específico"], float(fila["% NCA"]), fila["Estatus"]))
                            nuevas_paletas_lista.append({
                                "id_pbo": nuevo_id_pbo, "nro_ticket": fila["Nro Ticket"], "camadas_sueltas": n_camadas,
                                "defecto": fila["Defecto Específico"], "nca": float(fila["% NCA"]), "estatus": fila["Estatus"]
                            })
                            
                        conn.commit()
                        
                        # Optimistic Update en RAM
                        nueva_fila_lote = pd.DataFrame([{
                            "id_pbo": nuevo_id_pbo, "producto": prod, "formato": formato, "lote": lote_prod,
                            "orden": orden_prod, "fecha_produccion": str(fecha_p), "defecto_general": defecto_gen,
                            "cantidad_total_latas": int(total_latas), "ubicacion": "Almacen de PBO"
                        }])
                        st.session_state["lotes_df"] = pd.concat([st.session_state["lotes_df"], nueva_fila_lote], ignore_index=True)
                        st.session_state["paletas_df"] = pd.concat([st.session_state["paletas_df"], pd.DataFrame(nuevas_paletas_lista)], ignore_index=True)
                        
                        st.success(f"¡{nuevo_id_pbo} guardado exitosamente con sus unidades asociadas!")
                        st.rerun()
                    except Exception as e:
                        conn.rollback()
                        st.error(f"Error en inserción: {e}. Verifique si algún ticket ya se encuentra duplicado en planta.")
                    finally:
                        cursor.close()
                        conn.close()

        elif accion_calidad == "🔄 Actualización de Paletas":
            pbo_ver = st.selectbox("Filtra por PBO:", lotes_activos_df["id_pbo"])
            df_paletas_pbo = paletas_activas_df[paletas_activas_df["id_pbo"] == pbo_ver] if not paletas_activas_df.empty else pd.DataFrame()
            
            if df_paletas_pbo.empty: 
                st.warning("No hay paletas asignadas.")
            else:
                tickets_seleccionados = st.multiselect("Tickets a actualizar:", options=df_paletas_pbo["nro_ticket"].unique())
                if tickets_seleccionados:
                    mod_estatus = st.selectbox("Cambiar Estatus Operacional a:", ["-- No modificar estatus --"] + ESTATUS_OPCIONES)
                    escribir_nuevo_defecto = st.checkbox("Modificar defecto")
                    mod_defecto = st.text_input("Nuevo Defecto:", disabled=not escribir_nuevo_defecto)
                    mod_nca = st.number_input("Modificar % NCA (-1 para ignorar):", min_value=-1.0, value=-1.0)
                    mod_camadas = st.number_input("Actualizar Nro Camadas (-1 para ignorar):", min_value=-1, value=-1)
                    
                    if st.button("💾 Aplicar Cambios en Lote"):
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        
                        if mod_estatus != "-- No modificar estatus --":
                            cursor.execute("UPDATE paletas_db SET estatus = %s WHERE nro_ticket = ANY(%s);", (mod_estatus, tickets_seleccionados))
                            st.session_state["paletas_df"].loc[st.session_state["paletas_df"]["nro_ticket"].isin(tickets_seleccionados), "estatus"] = mod_estatus
                        if escribir_nuevo_defecto and mod_defecto:
                            cursor.execute("UPDATE paletas_db SET defecto = %s WHERE nro_ticket = ANY(%s);", (mod_defecto, tickets_seleccionados))
                            st.session_state["paletas_df"].loc[st.session_state["paletas_df"]["nro_ticket"].isin(tickets_seleccionados), "defecto"] = mod_defecto
                        if mod_nca != -1.0:
                            cursor.execute("UPDATE paletas_db SET nca = %s WHERE nro_ticket = ANY(%s);", (mod_nca, tickets_seleccionados))
                            st.session_state["paletas_df"].loc[st.session_state["paletas_df"]["nro_ticket"].isin(tickets_seleccionados), "nca"] = mod_nca
                        if mod_camadas != -1:
                            cursor.execute("UPDATE paletas_db SET camadas_sueltas = %s WHERE nro_ticket = ANY(%s);", (mod_camadas, tickets_seleccionados))
                            st.session_state["paletas_df"].loc[st.session_state["paletas_df"]["nro_ticket"].isin(tickets_seleccionados), "camadas_sueltas"] = int(mod_camadas)
                            
                        conn.commit()
                        cursor.close()
                        conn.close()
                        st.success("¡Base de datos y RAM local actualizadas en lote!")
                        st.rerun()

        elif accion_calidad == "🔬 Dictamen de Reproceso":
            pbo_evaluar = st.selectbox("Selecciona el PBO a dictaminar:", lotes_activos_df["id_pbo"])
            df_reproceso_pbo = reprocesos_activos_df[reprocesos_activos_df["id_pbo"] == pbo_evaluar] if not reprocesos_activos_df.empty else pd.DataFrame()
            
            if df_reproceso_pbo.empty: 
                st.warning("No cuenta con registros de paletas nuevas de reproceso.")
            else:
                tickets_evaluar = st.multiselect("Tickets de reproceso a dictaminar:", options=df_reproceso_pbo["nuevo_ticket_reprocesado"].unique())
                if tickets_evaluar:
                    nuevo_estatus_rep = st.selectbox("Estatus Dictamen Control de Calidad:", ESTATUS_DICTAMEN_CALIDAD)
                    observacion_lab = st.text_area("Observación Técnica:")
                    
                    if st.button("💾 Estampar Firma"):
                        if observacion_lab:
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            msg_firma = f"[{usuario}]: {observacion_lab}"
                            
                            cursor.execute("UPDATE reproceso_db SET estatus_calidad = %s, observacion_laboratorio = %s WHERE nuevo_ticket_reprocesado = ANY(%s);", (nuevo_estatus_rep, msg_firma, tickets_evaluar))
                            conn.commit()
                            cursor.close()
                            conn.close()
                            
                            st.session_state["reprocesos_df"].loc[st.session_state["reprocesos_df"]["nuevo_ticket_reprocesado"].isin(tickets_evaluar), "estatus_calidad"] = nuevo_estatus_rep
                            st.session_state["reprocesos_df"].loc[st.session_state["reprocesos_df"]["nuevo_ticket_reprocesado"].isin(tickets_evaluar), "observacion_laboratorio"] = msg_firma
                            
                            st.success("¡Dictamen grabado de manera masiva!")
                            st.rerun()

        elif accion_calidad == "🗑️ Eliminar PBO":
            pbo_a_borrar = st.selectbox("Selecciona el caso PBO a remover:", lotes_activos_df["id_pbo"])
            motivo_cancelacion = st.text_input("Escribe el motivo detallado (Obligatorio):")
            
            if st.button("❌ Confirmar Eliminación", type="primary"):
                if motivo_cancelacion:
                    conn = get_db_connection()
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    cursor.execute("SELECT * FROM lotes_db WHERE id_pbo = %s;", (pbo_a_borrar,))
                    lote_data = cursor.fetchone()
                    
                    try:
                        cursor.execute("INSERT INTO historico_pbo_db VALUES (%s, %s, %s, %s, %s, %s);", (pbo_a_borrar, lote_data["producto"], lote_data["lote"], datetime.now().strftime("%Y-%m-%d %H:%M"), f"Cancelado manual por Calidad. Motivo: {motivo_cancelacion}", usuario))
                        cursor.execute("DELETE FROM lotes_db WHERE id_pbo = %s;", (pbo_a_borrar,))
                        conn.commit()
                        
                        st.session_state["lotes_df"] = st.session_state["lotes_df"][st.session_state["lotes_df"]["id_pbo"] != pbo_a_borrar]
                        st.session_state["paletas_df"] = st.session_state["paletas_df"][st.session_state["paletas_df"]["id_pbo"] != pbo_a_borrar]
                        st.session_state["reprocesos_df"] = st.session_state["reprocesos_df"][st.session_state["reprocesos_df"]["id_pbo"] != pbo_a_borrar]
                        
                        nueva_fila_cancelada = pd.DataFrame([{
                            "id_pbo": pbo_a_borrar, "producto": lote_data["producto"], "lote": lote_data["lote"],
                            "fecha_cierre": datetime.now().strftime("%Y-%m-%d %H:%M"), "motivo_cierre": f"Cancelado: {motivo_cancelacion}", "operador_cierre": usuario
                        }])
                        st.session_state["historico_pbo_df"] = pd.concat([st.session_state["historico_pbo_df"], nueva_fila_cancelada], ignore_index=True)
                        
                        st.success("¡Caso removido de piso en 0.01 segundos!")
                        st.rerun()
                    except Exception as e:
                        conn.rollback()
                    finally:
                        cursor.close()
                        conn.close()

elif "Reproceso" in departamento:
    st.warning("🛠️ Permisos de Nivel: REPROCESO")
    if lotes_activos_df.empty: 
        st.info("No hay casos PBO abiertos.")
    else:
        pbo_target = st.selectbox("Selecciona el caso PBO asignado a tu línea", lotes_activos_df["id_pbo"])
        df_originales_pbo = paletas_activas_df[paletas_activas_df["id_pbo"] == pbo_target] if not paletas_activas_df.empty else pd.DataFrame()
        
        if df_originales_pbo.empty: 
            st.warning("Este caso no posee paletas cargadas.")
        else:
            tickets_consumidos = st.multiselect("Tickets ORIGINALES consumidos:", options=df_originales_pbo["nro_ticket"].unique())
        
            if tickets_consumidos:
                st.write("#### 📦 Desglose de Unidades GENERADAS (Post-Reproceso)")
                col_rep1, col_rep2 = st.columns(2)
                rep_paletas = col_rep1.number_input("Cantidad de Paletas Generadas", min_value=0, value=1, step=1)
                rep_camadas = col_rep2.number_input("Cantidad de Camadas Generadas", min_value=0, value=0, step=1)
                
                # --- 📋 FILAS DINÁMICAS EN REPROCESO ---
                tipos_rep_lista = ["Paleta"] * rep_paletas + ["Camada"] * rep_camadas
                df_plantilla_rep = pd.DataFrame({
                    "Tipo": tipos_rep_lista,
                    "Nuevo Ticket Reprocesado": [""] * len(tipos_rep_lista)
                })
                
                st.write("📋 **Asigne el número de ticket correspondiente generado:**")
                tabla_reproceso = st.data_editor(df_plantilla_rep, hide_index=True, use_container_width=True, disabled=["Tipo"])
                
                if st.button("🚀 Registrar Cierre de Línea"):
                    if "" in tabla_reproceso["Nuevo Ticket Reprocesado"].values: 
                        st.error("Error: Por favor, complete todos los campos de 'Nuevo Ticket Reprocesado'.")
                    else:
                        cadena_consumidos = ", ".join(tickets_consumidos)
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        error_save = False
                        nuevas_filas_rep = []
                        
                        try:
                            for _, fila in tabla_reproceso.iterrows():
                                n_camadas_rep = 0 if fila["Tipo"] == "Paleta" else 1
                                cursor.execute("INSERT INTO reproceso_db (id_pbo, tickets_originales_consumidos, nuevo_ticket_reprocesado, camadas_sueltas, estatus_calidad, estatus_logistica, observacion_laboratorio) VALUES (%s, %s, %s, %s, 'En Control de Calidad', 'En espera', 'Pendiente por evaluar');", (pbo_target, cadena_consumidos, fila["Nuevo Ticket Reprocesado"], n_camadas_rep))
                                nuevas_filas_rep.append({
                                    "id_pbo": pbo_target, "tickets_originales_consumidos": cadena_consumidos,
                                    "nuevo_ticket_reprocesado": fila["Nuevo Ticket Reprocesado"], "camadas_sueltas": n_camadas_rep,
                                    "estatus_calidad": "En Control de Calidad", "estatus_logistica": "En espera", "observacion_laboratorio": "Pendiente por evaluar"
                                })
                            
                            cursor.execute("UPDATE paletas_db SET estatus = 'Reprocesado' WHERE nro_ticket = ANY(%s);", (tickets_consumidos,))
                            conn.commit()
                            
                            st.session_state["paletas_df"].loc[st.session_state["paletas_df"]["nro_ticket"].isin(tickets_consumidos), "estatus"] = "Reprocesado"
                            st.session_state["reprocesos_df"] = pd.concat([st.session_state["reprocesos_df"], pd.DataFrame(nuevas_filas_rep)], ignore_index=True)
                        except Exception as e:
                            conn.rollback()
                            error_save = True
                            st.error(f"Error de base de datos: {e}")
                        finally:
                            cursor.close()
                            conn.close()
                            
                        if not error_save:
                            st.success("¡Lote de reproceso acoplado eficientemente!")
                            st.rerun()

elif "Logística" in departamento:
    st.info("📦 Permisos de Nivel: LOGÍSTICA")
    if lotes_activos_df.empty: 
        st.info("No hay casos PBO activos.")
    else:
        pbo_log = st.selectbox("Selecciona el PBO a gestionar:", lotes_activos_df["id_pbo"])
        nueva_ubica = st.selectbox("Reubicar lote físico completo:", UBICACIONES_LOGISTICA)
        df_rep_pbo = reprocesos_activos_df[reprocesos_activos_df["id_pbo"] == pbo_log] if not reprocesos_activos_df.empty else pd.DataFrame()
        
        if df_rep_pbo.empty:
            st.warning("Este caso aún no cuenta con paletas de reproceso.")
            tickets_log = []; nuevo_estado_log = "En espera"
        else:
            tickets_log = st.multiselect("Tickets nuevos validados en físico:", options=df_rep_pbo["nuevo_ticket_reprocesado"].unique())
            nuevo_estado_log = st.selectbox("Estatus de Verificación Logística:", ESTATUS_DICTAMEN_LOGISTICA)
        
        if st.button("💾 Confirmar Movimiento"):
            conn = get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("UPDATE lotes_db SET ubicacion = %s WHERE id_pbo = %s;", (nueva_ubica, pbo_log))
                st.session_state["lotes_df"].loc[st.session_state["lotes_df"]["id_pbo"] == pbo_log, "ubicacion"] = nueva_ubica
                
                if tickets_log:
                    cursor.execute("UPDATE reproceso_db SET estatus_logistica = %s WHERE nuevo_ticket_reprocesado = ANY(%s);", (nuevo_estado_log, tickets_log))
                    st.session_state["reprocesos_df"].loc[st.session_state["reprocesos_df"]["nuevo_ticket_reprocesado"].isin(tickets_log), "estatus_logistica"] = nuevo_estado_log
                    
                conn.commit()
                st.success("¡Inventario verificado y reubicado!")
                st.rerun()
            except Exception as e:
                pass
            finally:
                cursor.close()
                conn.close()

# ==========================================
# 7. SECCIÓN DE CONSULTA Y REPORTES
# ==========================================
st.divider()
st.subheader("🔍 Desglose de Piso y Auditoría")

filtro_global = st.selectbox("Filtrar paneles inferiores por caso PBO activo", ["Ver Todo"] + list(lotes_activos_df["id_pbo"]))
display_tab1, display_tab2, display_tab3 = st.tabs(["📋 Paletas Iniciales Retenidas", "🔄 Reprocesos Activos", "🏛️ Archivo de Auditoría Histórica"])

with display_tab1:
    df_f1 = paletas_activas_df if filtro_global == "Ver Todo" else paletas_activas_df[paletas_activas_df["id_pbo"] == filtro_global] if not paletas_activas_df.empty else pd.DataFrame()
    st.dataframe(df_f1, use_container_width=True, hide_index=True)

with display_tab2:
    if reprocesos_activos_df.empty: 
        st.info("No existen registros de paletas de reproceso.")
    else:
        df_f2 = reprocesos_activos_df if filtro_global == "Ver Todo" else reprocesos_activos_df[reprocesos_activos_df["id_pbo"] == filtro_global]
        st.dataframe(df_f2, use_container_width=True, hide_index=True)

with display_tab3:
    if historico_pbo_df.empty:
        st.info("El archivo histórico está vacío.")
    else:
        st.success("🏛️ Registro Inmutable de PBOs Liberados:")
        st.dataframe(historico_pbo_df, use_container_width=True, hide_index=True)
        
        st.divider()
        pbo_historico_consultar = st.selectbox("Selecciona un PBO cerrado para reconstrucción:", historico_pbo_df["id_pbo"].unique())
        
        if pbo_historico_consultar:
            conn = get_db_connection()
            df_paletas_historicas = pd.read_sql_query("SELECT * FROM historico_paletas_db WHERE id_pbo = %s", conn, params=[pbo_historico_consultar])
            df_reproceso_historico = pd.read_sql_query("SELECT * FROM historico_reproceso_db WHERE id_pbo = %s", conn, params=[pbo_historico_consultar])
            conn.close()
            
            macro_data = historico_pbo_df[historico_pbo_df["id_pbo"] == pbo_historico_consultar].iloc[0]
            
            with st.container(border=True):
                st.write(f"## 📜 REPORTE OFICIAL: {pbo_historico_consultar}")
                st.write(f"🏢 **Planta**: Empresas Polar S.A. | 📅 **Fecha**: `{macro_data['fecha_cierre']}`")
                st.write(f"📦 **Producto**: {macro_data['producto']} | 🏷️ **Lote**: `{macro_data['lote']}`")
                st.write(f"📌 **Dictamen**: *{macro_data['motivo_cierre']}*")
                st.dataframe(df_paletas_historicas, use_container_width=True, hide_index=True)