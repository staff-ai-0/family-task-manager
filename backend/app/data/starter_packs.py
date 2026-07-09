"""Age-preset + themed starter packs (P1-W3) — curated ES/MX chore, gig and
reward seeds.

Static and deterministic on purpose (BusyKid's age-preset chart is the
competitive reference: parents get a sensible board "in minutes" with zero
LLM cost/latency). A future enhancement can let Jarvis generate CUSTOM packs,
but the default onboarding path must never depend on an AI call.

Two kinds of pack live in the same catalog and flow through the identical
apply endpoint (band = dict key):
- AGE_BANDS   — the four age presets ("3-5" … "13+").
- THEMED_PACKS — need-based presets that cut across ages. First one: "tdah",
  a calming, routine-first pack for neurodivergent kids (the Spanish-language
  "rutinas / TDAH" angle documented in docs/SEO_ASO.md §2.4 is an unoccupied,
  high-empathy LATAM niche — Joon proves clinical/ADHD framing converts and
  retains parents). It intentionally matches the same shape/size contract as
  the age bands so the picker UI and the apply/idempotency logic need zero
  special-casing.

Two-currency economy rules (docs/superpowers/specs/2026-06-30):
- "chores"  → TaskTemplate rows (is_bonus=False) that earn POINTS.
- "gigs"    → GigOffering rows on the /gigs board; points here are CASH
              value (1 point = $1 MXN) settled via the gig approval flow.
- "rewards" → Reward rows redeemable with points (privileges — never cash).

Item ids are stable slugs so the apply endpoint can receive a checkbox
subset from the preview UI. Do not rename ids casually: they are the
contract with the frontend (and with idempotent re-applies only titles
matter, so renaming an id is safe for data but noisy for clients).

interval_days: 1=daily … 7=weekly (TaskTemplate weekly scheduling).
difficulty (gigs): 1=easy 2=medium 3=hard.
reward category: one of RewardCategory values (screen_time, treats,
activities, privileges, toys) — deliberately NO "money" rewards: only the
gig board converts effort to cash.
"""

AGE_BANDS = ("3-5", "6-8", "9-12", "13+")

# Need-based packs that cut across ages (applied through the same endpoint).
THEMED_PACKS = ("tdah",)

# Every valid band key the apply endpoint accepts (age presets + themed).
PACK_KEYS = AGE_BANDS + THEMED_PACKS

STARTER_PACKS: dict = {
    "3-5": {
        "label_es": "3 a 5 años",
        "label_en": "Ages 3-5",
        "tagline_es": "Hábitos pequeños con mucha celebración",
        "tagline_en": "Tiny habits, big celebrations",
        "chores": [
            {"id": "3-5.chore.juguetes", "title_es": "Recoger sus juguetes", "title_en": "Pick up your toys", "points": 5, "interval_days": 1},
            {"id": "3-5.chore.ropa-cesto", "title_es": "Poner la ropa sucia en el cesto", "title_en": "Put dirty clothes in the hamper", "points": 3, "interval_days": 1},
            {"id": "3-5.chore.zapatos", "title_es": "Guardar sus zapatos en su lugar", "title_en": "Put your shoes away", "points": 3, "interval_days": 1},
            {"id": "3-5.chore.dientes", "title_es": "Lavarse los dientes sin ayuda", "title_en": "Brush your teeth on your own", "points": 3, "interval_days": 1},
            {"id": "3-5.chore.cama-ayuda", "title_es": "Tender su cama (con ayuda)", "title_en": "Make your bed (with help)", "points": 4, "interval_days": 1},
            {"id": "3-5.chore.servilletas", "title_es": "Poner las servilletas en la mesa", "title_en": "Put the napkins on the table", "points": 3, "interval_days": 1},
            {"id": "3-5.chore.libros", "title_es": "Guardar los libros en su lugar", "title_en": "Put the books back on the shelf", "points": 3, "interval_days": 3},
            {"id": "3-5.chore.mascota-ayuda", "title_es": "Ayudar a dar de comer a la mascota", "title_en": "Help feed the pet", "points": 4, "interval_days": 1},
            {"id": "3-5.chore.pijama", "title_es": "Ponerse la pijama solito(a)", "title_en": "Put on your pajamas by yourself", "points": 3, "interval_days": 1},
        ],
        "gigs": [
            {"id": "3-5.gig.calcetines", "title_es": "Emparejar los calcetines limpios", "title_en": "Match the clean socks", "points": 10, "difficulty": 1, "category": "chores"},
            {"id": "3-5.gig.planta", "title_es": "Regar una planta", "title_en": "Water a plant", "points": 5, "difficulty": 1, "category": "outdoor"},
            {"id": "3-5.gig.coche-adentro", "title_es": "Ayudar a recoger el coche por dentro", "title_en": "Help tidy the inside of the car", "points": 15, "difficulty": 2, "category": "chores"},
            {"id": "3-5.gig.hojas", "title_es": "Juntar hojas del patio", "title_en": "Pick up leaves in the yard", "points": 10, "difficulty": 1, "category": "outdoor"},
        ],
        "rewards": [
            {"id": "3-5.reward.pantalla-30", "title_es": "30 minutos de tiempo de pantalla", "title_en": "30 minutes of screen time", "points_cost": 15, "category": "screen_time", "icon": "📱", "requires_approval": False},
            {"id": "3-5.reward.cuento", "title_es": "Elegir el cuento de la noche", "title_en": "Pick tonight's bedtime story", "points_cost": 10, "category": "privileges", "icon": "📚", "requires_approval": False},
            {"id": "3-5.reward.parque", "title_es": "Salida al parque", "title_en": "Trip to the park", "points_cost": 25, "category": "activities", "icon": "🛝", "requires_approval": True},
            {"id": "3-5.reward.dulce", "title_es": "Paleta o dulce sorpresa", "title_en": "Popsicle or surprise treat", "points_cost": 15, "category": "treats", "icon": "🍭", "requires_approval": False},
            {"id": "3-5.reward.pelicula", "title_es": "Elegir la película del viernes", "title_en": "Pick the Friday movie", "points_cost": 20, "category": "privileges", "icon": "🎬", "requires_approval": False},
            {"id": "3-5.reward.juego-mesa", "title_es": "Juego de mesa con mamá o papá", "title_en": "Board game with mom or dad", "points_cost": 20, "category": "activities", "icon": "🎲", "requires_approval": False},
        ],
    },
    "6-8": {
        "label_es": "6 a 8 años",
        "label_en": "Ages 6-8",
        "tagline_es": "Responsabilidades de verdad, a su medida",
        "tagline_en": "Real responsibilities, kid-sized",
        "chores": [
            {"id": "6-8.chore.cama", "title_es": "Tender su cama", "title_en": "Make your bed", "points": 5, "interval_days": 1},
            {"id": "6-8.chore.cuarto", "title_es": "Recoger su cuarto", "title_en": "Tidy your room", "points": 8, "interval_days": 3},
            {"id": "6-8.chore.mesa", "title_es": "Poner la mesa", "title_en": "Set the table", "points": 5, "interval_days": 1},
            {"id": "6-8.chore.mascota", "title_es": "Dar de comer a la mascota", "title_en": "Feed the pet", "points": 5, "interval_days": 1},
            {"id": "6-8.chore.tarea", "title_es": "Hacer la tarea sin recordatorios", "title_en": "Do homework without reminders", "points": 10, "interval_days": 1},
            {"id": "6-8.chore.plato", "title_es": "Llevar su plato al fregadero", "title_en": "Clear your plate to the sink", "points": 3, "interval_days": 1},
            {"id": "6-8.chore.mochila", "title_es": "Preparar su mochila para mañana", "title_en": "Pack your school bag for tomorrow", "points": 5, "interval_days": 1},
            {"id": "6-8.chore.doblar-ropa", "title_es": "Ayudar a doblar la ropa limpia", "title_en": "Help fold the clean laundry", "points": 8, "interval_days": 7},
            {"id": "6-8.chore.plantas", "title_es": "Regar las plantas", "title_en": "Water the plants", "points": 5, "interval_days": 3},
        ],
        "gigs": [
            {"id": "6-8.gig.lavar-coche", "title_es": "Ayudar a lavar el coche", "title_en": "Help wash the car", "points": 30, "difficulty": 2, "category": "chores"},
            {"id": "6-8.gig.barrer-patio", "title_es": "Barrer el patio", "title_en": "Sweep the patio", "points": 15, "difficulty": 1, "category": "outdoor"},
            {"id": "6-8.gig.librero", "title_es": "Organizar el librero", "title_en": "Organize the bookshelf", "points": 20, "difficulty": 2, "category": "chores"},
            {"id": "6-8.gig.banar-perro", "title_es": "Ayudar a bañar al perro", "title_en": "Help give the dog a bath", "points": 25, "difficulty": 2, "category": "chores"},
            {"id": "6-8.gig.vidrios", "title_es": "Limpiar los vidrios de abajo", "title_en": "Clean the low windows", "points": 15, "difficulty": 1, "category": "chores"},
        ],
        "rewards": [
            {"id": "6-8.reward.pantalla-30", "title_es": "30 minutos de tiempo de pantalla", "title_en": "30 minutes of screen time", "points_cost": 20, "category": "screen_time", "icon": "📱", "requires_approval": False},
            {"id": "6-8.reward.cena", "title_es": "Elegir la cena de la familia", "title_en": "Choose the family dinner", "points_cost": 30, "category": "privileges", "icon": "🌮", "requires_approval": False},
            {"id": "6-8.reward.parque", "title_es": "Salida al parque", "title_en": "Trip to the park", "points_cost": 25, "category": "activities", "icon": "🛝", "requires_approval": True},
            {"id": "6-8.reward.dormir-tarde", "title_es": "Dormirse 30 minutos más tarde", "title_en": "Stay up 30 minutes later", "points_cost": 25, "category": "privileges", "icon": "🌙", "requires_approval": False},
            {"id": "6-8.reward.postre", "title_es": "Postre especial", "title_en": "Special dessert", "points_cost": 20, "category": "treats", "icon": "🍦", "requires_approval": False},
            {"id": "6-8.reward.amigo", "title_es": "Invitar a un amigo a jugar", "title_en": "Have a friend over to play", "points_cost": 40, "category": "activities", "icon": "🧑‍🤝‍🧑", "requires_approval": True},
        ],
    },
    "9-12": {
        "label_es": "9 a 12 años",
        "label_en": "Ages 9-12",
        "tagline_es": "Autonomía y primeros encargos pagados",
        "tagline_en": "Autonomy and first paid jobs",
        "chores": [
            {"id": "9-12.chore.cama-cuarto", "title_es": "Tender su cama y recoger su cuarto", "title_en": "Make your bed and tidy your room", "points": 10, "interval_days": 1},
            {"id": "9-12.chore.platos", "title_es": "Lavar los platos", "title_en": "Wash the dishes", "points": 12, "interval_days": 2},
            {"id": "9-12.chore.basura", "title_es": "Sacar la basura", "title_en": "Take out the trash", "points": 8, "interval_days": 2},
            {"id": "9-12.chore.tarea", "title_es": "Hacer la tarea sin que se lo pidan", "title_en": "Do homework without being asked", "points": 10, "interval_days": 1},
            {"id": "9-12.chore.ropa", "title_es": "Doblar y guardar su ropa", "title_en": "Fold and put away your laundry", "points": 12, "interval_days": 7},
            {"id": "9-12.chore.cocina", "title_es": "Barrer o trapear la cocina", "title_en": "Sweep or mop the kitchen", "points": 12, "interval_days": 3},
            {"id": "9-12.chore.cena-ayuda", "title_es": "Ayudar a preparar la cena", "title_en": "Help make dinner", "points": 12, "interval_days": 3},
            {"id": "9-12.chore.perro", "title_es": "Pasear al perro", "title_en": "Walk the dog", "points": 10, "interval_days": 1},
            {"id": "9-12.chore.bano", "title_es": "Limpiar el lavabo y espejo del baño", "title_en": "Clean the bathroom sink and mirror", "points": 15, "interval_days": 7},
        ],
        "gigs": [
            {"id": "9-12.gig.coche-completo", "title_es": "Lavar el coche completo", "title_en": "Wash the whole car", "points": 50, "difficulty": 3, "category": "chores"},
            {"id": "9-12.gig.garage", "title_es": "Ayudar a ordenar el garage", "title_en": "Help clean out the garage", "points": 40, "difficulty": 3, "category": "chores"},
            {"id": "9-12.gig.alacena", "title_es": "Organizar la alacena", "title_en": "Organize the pantry", "points": 30, "difficulty": 2, "category": "chores"},
            {"id": "9-12.gig.vidrios-casa", "title_es": "Limpiar los vidrios de la casa", "title_en": "Clean the house windows", "points": 35, "difficulty": 2, "category": "chores"},
            {"id": "9-12.gig.mandado", "title_es": "Hacer un mandado a la tienda", "title_en": "Run an errand to the corner store", "points": 20, "difficulty": 1, "category": "errands"},
            {"id": "9-12.gig.hermano-tarea", "title_es": "Ayudar a un hermano con su tarea", "title_en": "Help a sibling with homework", "points": 25, "difficulty": 2, "category": "learning"},
        ],
        "rewards": [
            {"id": "9-12.reward.pantalla-60", "title_es": "1 hora de tiempo de pantalla", "title_en": "1 hour of screen time", "points_cost": 30, "category": "screen_time", "icon": "🎮", "requires_approval": False},
            {"id": "9-12.reward.cena", "title_es": "Elegir la cena de la familia", "title_en": "Choose the family dinner", "points_cost": 30, "category": "privileges", "icon": "🌮", "requires_approval": False},
            {"id": "9-12.reward.pizza", "title_es": "Noche de pizza", "title_en": "Pizza night", "points_cost": 50, "category": "treats", "icon": "🍕", "requires_approval": True},
            {"id": "9-12.reward.desvelo", "title_es": "Dormirse 1 hora más tarde el fin de semana", "title_en": "Stay up 1 hour later on the weekend", "points_cost": 35, "category": "privileges", "icon": "🌙", "requires_approval": False},
            {"id": "9-12.reward.cine", "title_es": "Salida al cine", "title_en": "Movie theater outing", "points_cost": 80, "category": "activities", "icon": "🎬", "requires_approval": True},
            {"id": "9-12.reward.sin-quehaceres", "title_es": "Un día sin quehaceres", "title_en": "A day off from chores", "points_cost": 60, "category": "privileges", "icon": "🏖️", "requires_approval": True},
        ],
    },
    "13+": {
        "label_es": "13 años o más",
        "label_en": "Ages 13+",
        "tagline_es": "Independencia con responsabilidades reales",
        "tagline_en": "Independence with real responsibilities",
        "chores": [
            {"id": "13+.chore.cuarto", "title_es": "Mantener su cuarto limpio", "title_en": "Keep your room clean", "points": 10, "interval_days": 1},
            {"id": "13+.chore.lavar-ropa", "title_es": "Lavar su propia ropa", "title_en": "Do your own laundry", "points": 15, "interval_days": 7},
            {"id": "13+.chore.cocinar", "title_es": "Cocinar una comida para la familia", "title_en": "Cook one meal for the family", "points": 20, "interval_days": 7},
            {"id": "13+.chore.trastes", "title_es": "Lavar los trastes después de cenar", "title_en": "Do the dishes after dinner", "points": 12, "interval_days": 2},
            {"id": "13+.chore.basura", "title_es": "Sacar la basura y el reciclaje", "title_en": "Take out the trash and recycling", "points": 8, "interval_days": 2},
            {"id": "13+.chore.aspirar", "title_es": "Aspirar la sala", "title_en": "Vacuum the living room", "points": 10, "interval_days": 3},
            {"id": "13+.chore.despensa", "title_es": "Acompañar y ayudar con la despensa", "title_en": "Help with the grocery run", "points": 12, "interval_days": 7},
            {"id": "13+.chore.estudio", "title_es": "Cumplir su plan de estudio de la semana", "title_en": "Complete your weekly study plan", "points": 20, "interval_days": 7},
        ],
        "gigs": [
            {"id": "13+.gig.ninera", "title_es": "Cuidar a los hermanos una tarde", "title_en": "Babysit siblings for an evening", "points": 100, "difficulty": 3, "category": "other"},
            {"id": "13+.gig.coche-full", "title_es": "Lavar y aspirar el coche", "title_en": "Wash and vacuum the car", "points": 60, "difficulty": 3, "category": "chores"},
            {"id": "13+.gig.refri", "title_es": "Limpiar el refrigerador a fondo", "title_en": "Deep-clean the fridge", "points": 50, "difficulty": 2, "category": "chores"},
            {"id": "13+.gig.pasto", "title_es": "Podar el pasto", "title_en": "Mow the lawn", "points": 70, "difficulty": 3, "category": "outdoor"},
            {"id": "13+.gig.despensa-solo", "title_es": "Hacer las compras de la semana", "title_en": "Do the weekly shopping run", "points": 40, "difficulty": 2, "category": "errands"},
            {"id": "13+.gig.abuelos-tech", "title_es": "Ayudar a los abuelos con la tecnología", "title_en": "Tech help for the grandparents", "points": 30, "difficulty": 1, "category": "learning"},
        ],
        "rewards": [
            {"id": "13+.reward.videojuegos", "title_es": "2 horas de videojuegos el fin de semana", "title_en": "2 hours of gaming on the weekend", "points_cost": 40, "category": "screen_time", "icon": "🎮", "requires_approval": False},
            {"id": "13+.reward.amigos", "title_es": "Salida con amigos", "title_en": "Outing with friends", "points_cost": 80, "category": "activities", "icon": "🎉", "requires_approval": True},
            {"id": "13+.reward.cena-viernes", "title_es": "Elegir la cena del viernes", "title_en": "Pick Friday's dinner", "points_cost": 30, "category": "privileges", "icon": "🌮", "requires_approval": False},
            {"id": "13+.reward.desvelo", "title_es": "Noche de desvelo el fin de semana", "title_en": "Weekend late night", "points_cost": 50, "category": "privileges", "icon": "🌙", "requires_approval": False},
            {"id": "13+.reward.musica", "title_es": "Elegir la música del coche una semana", "title_en": "Pick the car music for a week", "points_cost": 25, "category": "privileges", "icon": "🎵", "requires_approval": False},
            {"id": "13+.reward.cine-amigo", "title_es": "Ir al cine con un amigo", "title_en": "Movies with a friend", "points_cost": 90, "category": "activities", "icon": "🎬", "requires_approval": True},
        ],
    },
    # ── Themed: TDAH / rutinas (neurodivergent-friendly) ─────────────────────
    # Calm, visual, small-and-frequent-win routines. Chores earn POINTS (the
    # dopamine loop that pairs with the pet), gigs are gentle structured extra
    # jobs, rewards lean on privileges/sensory/1-on-1 time — never cash. Copy is
    # ES-first (docs/SEO_ASO.md §2.4: "rutinas para niños con TDAH").
    "tdah": {
        "label_es": "TDAH y rutinas",
        "label_en": "ADHD & routines",
        "tagline_es": "Rutinas visuales y calmadas, con logros pequeños y frecuentes",
        "tagline_en": "Calm, visual routines with small, frequent wins",
        "chores": [
            {"id": "tdah.chore.rutina-manana", "title_es": "Rutina de la mañana: vestirse, desayunar y dientes", "title_en": "Morning routine: dress, breakfast and teeth", "points": 6, "interval_days": 1},
            {"id": "tdah.chore.mochila-noche", "title_es": "Preparar la mochila la noche anterior", "title_en": "Pack your backpack the night before", "points": 5, "interval_days": 1},
            {"id": "tdah.chore.ropa-lista", "title_es": "Dejar lista la ropa de mañana", "title_en": "Lay out tomorrow's clothes", "points": 4, "interval_days": 1},
            {"id": "tdah.chore.tablero-visual", "title_es": "Marcar tus tareas en el tablero visual", "title_en": "Check off your tasks on the visual board", "points": 4, "interval_days": 1},
            {"id": "tdah.chore.escritorio-tarea", "title_es": "Despejar el escritorio antes de la tarea", "title_en": "Clear your desk before homework", "points": 5, "interval_days": 1},
            {"id": "tdah.chore.descanso-movimiento", "title_es": "Tomar un descanso de movimiento de 5 minutos", "title_en": "Take a 5-minute movement break", "points": 3, "interval_days": 1},
            {"id": "tdah.chore.rutina-noche", "title_es": "Rutina de la noche: guardar pantallas, pijama y cuento", "title_en": "Evening wind-down: screens away, pajamas, story", "points": 6, "interval_days": 1},
            {"id": "tdah.chore.una-cosa", "title_es": "Guardar una cosa antes de sacar otra", "title_en": "Put one thing away before taking out another", "points": 3, "interval_days": 1},
            {"id": "tdah.chore.plan-semana", "title_es": "Armar el plan visual de la semana con un adulto", "title_en": "Build the weekly visual plan with an adult", "points": 8, "interval_days": 7},
        ],
        "gigs": [
            {"id": "tdah.gig.cajon-pasos", "title_es": "Ordenar un cajón siguiendo una lista de pasos", "title_en": "Organize a drawer with a step-by-step checklist", "points": 20, "difficulty": 1, "category": "chores"},
            {"id": "tdah.gig.cartel-rutina", "title_es": "Crear un cartel de rutina para el refri", "title_en": "Make a routine poster for the fridge", "points": 25, "difficulty": 2, "category": "creative"},
            {"id": "tdah.gig.etiquetar-cajas", "title_es": "Etiquetar cajas o repisas para organizar", "title_en": "Label bins or shelves to stay organized", "points": 25, "difficulty": 2, "category": "creative"},
            {"id": "tdah.gig.regar-recordatorio", "title_es": "Regar las plantas siguiendo un recordatorio", "title_en": "Water the plants on a reminder", "points": 15, "difficulty": 1, "category": "outdoor"},
            {"id": "tdah.gig.loncheras-semana", "title_es": "Preparar las loncheras de la semana", "title_en": "Prep the week's lunchboxes", "points": 30, "difficulty": 2, "category": "chores"},
        ],
        "rewards": [
            {"id": "tdah.reward.tiempo-juego", "title_es": "20 minutos extra de tu juego favorito", "title_en": "20 extra minutes of your favorite game", "points_cost": 20, "category": "screen_time", "icon": "🎮", "requires_approval": False},
            {"id": "tdah.reward.tiempo-1a1", "title_es": "Tiempo especial 1 a 1 con mamá o papá", "title_en": "Special 1-on-1 time with mom or dad", "points_cost": 25, "category": "activities", "icon": "💛", "requires_approval": False},
            {"id": "tdah.reward.musica-coche", "title_es": "Elegir la música del coche", "title_en": "Pick the car music", "points_cost": 15, "category": "privileges", "icon": "🎵", "requires_approval": False},
            {"id": "tdah.reward.caja-sensorial", "title_es": "Caja sensorial sorpresa (fidget o plastilina)", "title_en": "Surprise sensory box (fidget or putty)", "points_cost": 30, "category": "toys", "icon": "🧩", "requires_approval": True},
            {"id": "tdah.reward.pelicula-pijama", "title_es": "Noche de película en pijama", "title_en": "Movie night in pajamas", "points_cost": 35, "category": "activities", "icon": "🎬", "requires_approval": True},
            {"id": "tdah.reward.comodin-tarea", "title_es": "Comodín para saltarte una tarea", "title_en": "A wildcard to skip one chore", "points_cost": 40, "category": "privileges", "icon": "🃏", "requires_approval": True},
        ],
    },
}
