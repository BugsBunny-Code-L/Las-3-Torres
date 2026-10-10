# Las 3 Torres — manual de operación

Todo lo que necesitas saber para echarlo a andar y mantenerlo.
No hace falta programar. Son clics, copiar y pegar.

---

## Qué es cada archivo

| Archivo | Para qué sirve | ¿Lo tocas tú? |
|---|---|---|
| `actualizar.py` | El cerebro. Trae los datos, calcula los pronósticos y escribe la página. | No |
| `plantilla.html` | El diseño de la página. | Solo si quieres cambiar cómo se ve |
| `ojo-reportero.json` | **Tus notas.** Lo que ninguna base de datos tiene. | **Sí, seguido** |
| `index.html` | La página terminada. Se reescribe sola en cada corrida. | No |
| `datos/partidos.json` | La memoria: todos los partidos que ha visto el sistema. | No |
| `datos/pronosticos.json` | El registro de pronósticos que alimenta la calificación. | No |
| `.github/workflows/actualizar.yml` | La instrucción de "corre esto todos los días". | No |

Hay dos archivos que **nunca** debes borrar: `datos/partidos.json` y `datos/pronosticos.json`. El primero es toda la historia que el sistema ha aprendido; el segundo es tu registro de aciertos. Si los borras, empiezas de cero.

---

## Puesta en marcha, una sola vez

Calcula unos 40 minutos. Se hace todo desde el navegador.

### 1. Crea tu cuenta de GitHub
Entra a `github.com` y regístrate. Es gratis. Guarda bien tu usuario y contraseña.

### 2. Crea el repositorio
Arriba a la derecha, el botón **+** y luego **New repository**.

- En **Repository name** escribe: `las-3-torres`
- Déjalo en **Public** (es lo que permite que la página sea gratis)
- Marca la casilla **Add a README file**
- Botón verde **Create repository**

### 3. Sube los archivos
Dentro del repositorio, botón **Add file** y luego **Upload files**.

Arrastra estos cuatro:
`actualizar.py`, `plantilla.html`, `ojo-reportero.json`, `INSTRUCCIONES.md`

Abajo, botón verde **Commit changes**.

### 4. Sube la automatización
Este va en una carpeta especial. En el repositorio, **Add file** y luego **Create new file**.

En la barra del nombre escribe exactamente esto, con las diagonales:

```
.github/workflows/actualizar.yml
```

Al escribir las diagonales verás que se van creando carpetas solas. Luego abre el archivo `actualizar.yml` que te pasé, copia **todo** su contenido y pégalo en el cuadro grande. Botón verde **Commit changes**.

### 5. Enciende los permisos
Pestaña **Settings** (arriba), menú **Actions** del lado izquierdo, submenú **General**.

Baja hasta **Workflow permissions** y marca **Read and write permissions**. Botón **Save**.

> Sin este paso el programa corre pero no puede guardar nada. Es el error más común.

### 6. Prende la página
Pestaña **Settings**, menú **Pages** del lado izquierdo.

- En **Source** elige **Deploy from a branch**
- En **Branch** elige `main` y carpeta `/ (root)`
- Botón **Save**

GitHub te va a dar tu dirección. Se ve así:
`https://TUUSUARIO.github.io/las-3-torres/`

Guárdala en favoritos del celular. Esa es tu página.

### 7. La primera corrida
Pestaña **Actions**, en la lista de la izquierda elige **Actualizar Las 3 Torres**, y a la derecha el botón **Run workflow**, y otra vez **Run workflow**.

**La primera vez tarda entre 15 y 30 minutos** porque está bajando cinco meses de historia de las nueve ligas. Las siguientes tardan dos o tres minutos. Puedes cerrar la ventana, sigue corriendo solo.

Cuando aparezca la palomita verde, abre tu dirección. Ahí está.

---

## El día a día

No tienes que hacer nada. Todos los días a las 6:47 de la mañana se actualiza solo.

Si quieres que corra en ese momento: pestaña **Actions**, **Actualizar Las 3 Torres**, **Run workflow**.

---

## Escribir en el ojo reportero

Esta es tu parte y es la que distingue al sistema de cualquier página de estadísticas.

En el repositorio abre `ojo-reportero.json`, dale al lápiz de arriba a la derecha, edita y **Commit changes**. Entra en el cálculo en la siguiente corrida.

Cada nota se ve así:

```json
  {
    "equipo": "Cruz Azul",
    "titulo": "Referente con bajo rendimiento en entrenamientos por tema personal",
    "detalle": "Tres semanas sin completar sesiones completas.",
    "efecto": "perjudica",
    "fuerza": "algo",
    "hasta": "2026-11-15"
  }
```

**Qué va en cada campo:**

- `equipo` — el nombre como aparece en la página. Si no coincide, la nota se ignora en silencio.
- `titulo` — lo que se lee en la ficha. Corto y en neutro.
- `detalle` — el sustento. Por qué eso cambia el partido.
- `efecto` — `perjudica` o `favorece` a ese equipo.
- `fuerza` — `poco`, `algo` o `bastante`.
- `hasta` — fecha en que la nota deja de contar, en formato año-mes-día. **Siempre ponla.** Una gripa no dura tres meses, y sin fecha la nota se queda pesando para siempre.

**Las reglas del formato.** Las notas van entre corchetes `[ ]`, cada una entre llaves `{ }`, separadas por comas, **menos la última, que no lleva coma**. Si rompes esto el programa se detiene y te avisa en Actions. Si te enredas, pégame el archivo y te lo acomodo.

### Cómo escribirlas sin exponer a nadie

Tu página es pública y los jugadores son personas reales. Escribe el efecto, no el chisme.

| Así no | Así sí |
|---|---|
| "Se está divorciando de su esposa" | "Atraviesa una situación personal que afectó su preparación" |
| "Llegó borracho al entrenamiento" | "Faltó a la sesión del miércoles por razones disciplinarias" |
| "Se peleó a golpes con el técnico" | "Tensión reportada entre el jugador y el cuerpo técnico" |

El factor pesa exactamente igual en el cálculo. Lo único que cambia es que nadie queda señalado por algo que no está verificado.

---

## El tope del 25%

Por más notas que escribas, el ojo reportero nunca puede pesar más de la cuarta parte del ajuste total. Si te pasas, el programa las encoge solo y la ficha te avisa con el medidor.

Si quieres moverlo, en `actualizar.py` está la línea:

```python
TOPE_REPORTERO  = 0.25
```

Cámbiala a `0.30` o a `0.20`. Yo esperaría a tener dos meses de calificación antes de tocarla: la tabla de "qué tipo de factor está ayudando" te va a decir si tus notas están acertando o no.

---

## Otros números que puedes mover

Todos están juntos, al principio de `actualizar.py`:

```python
DIAS_ADELANTE   = 8      # cuántos días de partidos futuros traer
DIAS_ATRAS      = 4      # cuántos días recientes revisar en cada corrida
DIAS_PRIMERA    = 150    # cuánta historia traer la primera vez
```

Subir `DIAS_ADELANTE` a 14 te da más partidos por adelantado y tarda un poco más.

---

## Cuando algo falla

**La corrida sale con tache rojo.** Pestaña Actions, entra a la corrida fallida y lee el último renglón rojo. Si dice algo de `json`, es que `ojo-reportero.json` tiene una coma de más o de menos. Si dice `permission denied`, te faltó el paso 5.

**La página no abre.** Después de prender Pages puede tardar 10 minutos la primera vez. Revisa que la dirección lleve la diagonal al final.

**Un equipo dice "sin partido".** Es normal fuera de temporada o si su próximo juego cae más allá de los 8 días. La NBA empieza en octubre, la NFL en septiembre, la MLB en marzo.

**Los pronósticos salen raros las primeras semanas.** También es normal. El modelo necesita partidos para aprender. Con menos de ocho por equipo se apoya más en el promedio de la liga, y la ficha te lo dice en "Lo que el modelo no sabe".

---

## Qué revisar en un mes

Cuando la sección "Cómo va el modelo" tenga cincuenta o más pronósticos cerrados, la gráfica de calibración empieza a servir. Eso es lo que hay que mirar:

Si la barra vino y la barra gris quedan parejas en cada banda, los porcentajes son confiables. Si la vino siempre va más alta que la gris, el modelo es optimista y hay que bajarle. Si pasa al revés, es tímido.

Y en la tabla de tipos de factor: lo que salga en gris está apuntando al equipo equivocado más de la mitad de las veces. Ahí me dices y le bajamos el peso.
