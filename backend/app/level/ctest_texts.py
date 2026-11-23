"""C-test passages, written for Lingo OS, graded A2 → C1.

The first and last sentences stay intact; gaps are made in the sentences between them.
Japanese needs a character-level variant and is not included yet.
"""

TEXTS: dict[str, dict[str, str]] = {
    "de": {
        "A2": (
            "Am Samstag gehe ich oft auf den Markt. Dort kaufe ich frisches Obst und Gemüse für die ganze Woche. "
            "Die Verkäufer sind meistens sehr freundlich und manchmal bekomme ich einen Apfel geschenkt. "
            "Nach dem Einkaufen trinke ich gern einen Kaffee in einem kleinen Café an der Ecke. "
            "Wenn das Wetter schön ist, sitze ich draußen und beobachte die Leute. "
            "Am Nachmittag koche ich dann etwas Leckeres für meine Freunde."
        ),
        "B1": (
            "Viele Menschen in Deutschland fahren jeden Tag mit dem Zug zur Arbeit. "
            "Das ist oft bequemer als mit dem Auto, weil man unterwegs lesen oder Musik hören kann. "
            "Allerdings kommen die Züge nicht immer pünktlich, und bei schlechtem Wetter fallen manche Verbindungen sogar ganz aus. "
            "Deshalb planen viele Pendler lieber etwas mehr Zeit ein. "
            "Trotzdem sind die meisten mit dem Angebot zufrieden, besonders seit es günstigere Monatskarten gibt. "
            "Für die Umwelt ist die Bahn auf jeden Fall die bessere Wahl."
        ),
        "B2": (
            "Immer mehr Unternehmen erlauben ihren Mitarbeitenden, einen Teil der Woche von zu Hause aus zu arbeiten. "
            "Befürworter betonen, dass dadurch lange Arbeitswege entfallen und sich Beruf und Familie leichter vereinbaren lassen. "
            "Kritiker hingegen befürchten, dass der persönliche Austausch im Team darunter leidet und neue Kolleginnen und "
            "Kollegen schwerer eingearbeitet werden können. "
            "Studien zeigen bislang ein gemischtes Bild: Die Produktivität bleibt häufig stabil, doch das Gefühl der "
            "Zugehörigkeit nimmt ab. "
            "Viele Firmen setzen deshalb auf hybride Modelle, die beide Seiten berücksichtigen."
        ),
        "C1": (
            "Die Frage, inwieweit Sprache unser Denken prägt, beschäftigt Wissenschaftler seit Jahrzehnten. "
            "Während frühere Theorien davon ausgingen, dass die Muttersprache die Wahrnehmung der Welt weitgehend bestimmt, "
            "vertreten heutige Forschende eine deutlich zurückhaltendere Position. "
            "Experimente legen nahe, dass sprachliche Kategorien zwar bestimmte Unterscheidungen erleichtern, grundlegende "
            "kognitive Fähigkeiten jedoch kaum einschränken. "
            "Bemerkenswert ist allerdings, dass mehrsprachige Menschen je nach verwendeter Sprache leicht unterschiedliche "
            "Entscheidungen treffen. "
            "Dieser Befund wirft die Frage auf, ob Mehrsprachigkeit nicht nur ein kommunikativer, sondern auch ein kognitiver Vorteil ist."
        ),
    },
    "es": {
        "A2": (
            "Los domingos me gusta desayunar con mi familia. "
            "Mi madre prepara café y mi hermano compra pan en la panadería de la esquina. "
            "Después del desayuno, salimos a dar un paseo por el parque que está cerca de nuestra casa. "
            "Allí siempre hay muchos niños jugando y personas mayores que leen el periódico. "
            "A veces nos sentamos en un banco y hablamos durante horas. "
            "Por la tarde, normalmente vemos una película juntos."
        ),
        "B1": (
            "Cada vez más jóvenes deciden pasar un año en el extranjero antes de empezar la universidad. "
            "Para muchos de ellos es una oportunidad única de aprender otro idioma y conocer culturas diferentes. "
            "Sin embargo, no siempre es fácil adaptarse a una nueva rutina lejos de la familia y los amigos. "
            "Algunos estudiantes trabajan como voluntarios, mientras que otros prefieren buscar un empleo temporal para "
            "ganar algo de dinero. "
            "Al volver, la mayoría afirma que la experiencia les ha cambiado la forma de ver el mundo."
        ),
        "B2": (
            "El turismo masivo se ha convertido en un problema para numerosas ciudades europeas. "
            "Aunque los visitantes aportan ingresos importantes, los vecinos se quejan del ruido, del aumento de los "
            "alquileres y de la pérdida de comercios tradicionales. "
            "Algunos ayuntamientos han empezado a limitar el número de pisos turísticos e incluso a cobrar una tasa a "
            "quienes pasan solo unas horas en la ciudad. "
            "Los defensores de estas medidas sostienen que son necesarias para proteger la vida de barrio. "
            "Sus críticos, en cambio, advierten de que podrían perjudicar a la economía local."
        ),
        "C1": (
            "La creciente presencia de la inteligencia artificial en la vida cotidiana plantea interrogantes que van "
            "mucho más allá de lo puramente técnico. "
            "Si bien estas herramientas permiten automatizar tareas tediosas y agilizar procesos complejos, también "
            "suscitan dudas sobre la privacidad, la autoría y la responsabilidad en caso de error. "
            "Numerosos expertos reclaman un marco normativo que garantice la transparencia de los algoritmos sin frenar la innovación. "
            "Otros, en cambio, consideran que la regulación siempre irá a la zaga de una tecnología que evoluciona a un ritmo vertiginoso. "
            "Lo cierto es que el debate apenas ha comenzado."
        ),
    },
}

LEVELS = ("A2", "B1", "B2", "C1")
