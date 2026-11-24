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
    "fr": {
        "A2": (
            "Le samedi, je vais souvent au marché. "
            "J'y achète des fruits et des légumes frais pour toute la semaine. "
            "Les vendeurs sont très gentils et parfois ils me donnent une pomme en plus. "
            "Après les courses, je bois un café dans un petit bar au coin de la rue. "
            "Quand il fait beau, je m'assois dehors et je regarde les gens passer. "
            "L'après-midi, je prépare un bon repas pour mes amis."
        ),
        "B1": (
            "En France, beaucoup de gens prennent le train tous les jours pour aller travailler. "
            "C'est souvent plus pratique que la voiture, parce qu'on peut lire ou écouter de la musique pendant le trajet. "
            "Pourtant, les trains ne sont pas toujours à l'heure, et certaines lignes sont parfois supprimées à cause des grèves. "
            "C'est pourquoi de nombreux voyageurs prévoient un peu plus de temps le matin. "
            "Malgré tout, la plupart des usagers sont plutôt satisfaits, surtout depuis que les abonnements coûtent moins cher. "
            "Pour l'environnement, le train reste de toute façon le meilleur choix."
        ),
        "B2": (
            "De plus en plus d'entreprises permettent à leurs salariés de travailler une partie de la semaine depuis chez eux. "
            "Ce changement, accéléré par la pandémie, présente des avantages évidents : moins de temps perdu dans les transports et davantage de liberté pour organiser sa journée. "
            "Cependant, certains employés regrettent le contact quotidien avec leurs collègues et ont du mal à séparer vie professionnelle et vie privée. "
            "Les managers, de leur côté, doivent apprendre à évaluer le travail sur les résultats plutôt que sur la présence au bureau. "
            "Selon plusieurs études, un modèle mixte semble aujourd'hui le plus apprécié. "
            "Reste à savoir si cette organisation durera à long terme."
        ),
        "C1": (
            "L'intelligence artificielle s'invite désormais dans des domaines que l'on croyait réservés à l'humain, de la traduction à la création artistique. "
            "Ses partisans y voient un outil formidable, capable de libérer les individus des tâches répétitives et de démocratiser l'accès au savoir. "
            "Ses détracteurs, en revanche, redoutent une concentration inédite du pouvoir entre les mains de quelques géants technologiques, ainsi qu'une remise en cause profonde de nombreux métiers. "
            "Entre ces deux visions, les législateurs tentent d'élaborer un cadre qui encourage l'innovation sans sacrifier la protection des citoyens. "
            "La tâche s'avère d'autant plus ardue que la technologie évolue bien plus vite que le droit. "
            "Une chose est sûre : le débat ne fait que commencer."
        ),
    },
    "it": {
        "A2": (
            "Il sabato vado spesso al mercato. "
            "Lì compro frutta e verdura fresca per tutta la settimana. "
            "I venditori sono molto gentili e a volte mi regalano una mela. "
            "Dopo la spesa bevo un caffè in un piccolo bar all'angolo. "
            "Quando c'è il sole mi siedo fuori e guardo la gente che passa. "
            "Il pomeriggio cucino qualcosa di buono per i miei amici."
        ),
        "B1": (
            "In Italia molte persone prendono il treno ogni giorno per andare al lavoro. "
            "Spesso è più comodo della macchina, perché durante il viaggio si può leggere o ascoltare la musica. "
            "Però i treni non sono sempre puntuali, e quando c'è uno sciopero alcune corse vengono cancellate. "
            "Per questo motivo tanti pendolari partono di casa un po' prima. "
            "Nonostante tutto, la maggior parte dei viaggiatori è abbastanza soddisfatta, soprattutto da quando gli abbonamenti costano meno. "
            "Per l'ambiente, comunque, il treno resta la scelta migliore."
        ),
        "B2": (
            "Sempre più aziende permettono ai propri dipendenti di lavorare da casa per una parte della settimana. "
            "Questo cambiamento, accelerato dalla pandemia, offre vantaggi evidenti: meno tempo perso negli spostamenti e più libertà nell'organizzare la giornata. "
            "Tuttavia, alcuni lavoratori sentono la mancanza del contatto quotidiano con i colleghi e faticano a separare la vita professionale da quella privata. "
            "I responsabili, dal canto loro, devono imparare a valutare il lavoro in base ai risultati e non alla presenza in ufficio. "
            "Secondo diversi studi, oggi il modello misto è quello più apprezzato. "
            "Resta da vedere se questa organizzazione durerà nel tempo."
        ),
        "C1": (
            "L'intelligenza artificiale sta entrando in ambiti che si credevano riservati all'essere umano, dalla traduzione alla creazione artistica. "
            "I suoi sostenitori la considerano uno strumento straordinario, in grado di liberare le persone dai compiti ripetitivi e di rendere il sapere più accessibile. "
            "I critici, invece, temono una concentrazione di potere senza precedenti nelle mani di pochi colossi tecnologici, oltre a un profondo ripensamento di molte professioni. "
            "Tra queste due visioni, i legislatori cercano di definire un quadro che favorisca l'innovazione senza sacrificare la tutela dei cittadini. "
            "Il compito è tanto più arduo quanto più la tecnologia evolve rapidamente rispetto al diritto. "
            "Una cosa è certa: il dibattito è appena cominciato."
        ),
    },
    "pt": {
        "A2": (
            "Aos sábados eu costumo ir à feira. "
            "Lá eu compro frutas e verduras frescas para a semana inteira. "
            "Os feirantes são muito simpáticos e às vezes me dão uma fruta de presente. "
            "Depois das compras, tomo um café numa padaria pequena na esquina. "
            "Quando faz sol, sento do lado de fora e fico olhando as pessoas passarem. "
            "À tarde, preparo uma comida gostosa para os meus amigos."
        ),
        "B1": (
            "No Brasil, muita gente pega ônibus ou metrô todos os dias para ir ao trabalho. "
            "Muitas vezes é mais prático do que o carro, porque dá para ler ou ouvir música durante a viagem. "
            "Mas o transporte público nem sempre é pontual, e nos horários de pico os vagões ficam muito cheios. "
            "Por isso, muitos passageiros saem de casa um pouco mais cedo. "
            "Mesmo assim, boa parte dos usuários está satisfeita, principalmente desde que novas linhas foram inauguradas. "
            "Para o meio ambiente, o transporte coletivo continua sendo a melhor escolha."
        ),
        "B2": (
            "Cada vez mais empresas permitem que os funcionários trabalhem de casa durante parte da semana. "
            "Essa mudança, acelerada pela pandemia, traz vantagens evidentes: menos tempo perdido no trânsito e mais liberdade para organizar o dia. "
            "No entanto, alguns profissionais sentem falta do contato diário com os colegas e têm dificuldade em separar a vida profissional da vida pessoal. "
            "Os gestores, por sua vez, precisam aprender a avaliar o trabalho pelos resultados, e não pela presença no escritório. "
            "Segundo vários estudos, o modelo híbrido é hoje o mais valorizado. "
            "Resta saber se essa forma de organização vai durar a longo prazo."
        ),
        "C1": (
            "A inteligência artificial está chegando a áreas que se julgavam exclusivas do ser humano, da tradução à criação artística. "
            "Os seus defensores veem nela uma ferramenta extraordinária, capaz de livrar as pessoas de tarefas repetitivas e de democratizar o acesso ao conhecimento. "
            "Os críticos, por outro lado, temem uma concentração de poder sem precedentes nas mãos de poucas gigantes da tecnologia, além de uma profunda transformação de inúmeras profissões. "
            "Entre essas duas visões, os legisladores tentam construir um marco que estimule a inovação sem sacrificar a proteção dos cidadãos. "
            "A tarefa revela-se ainda mais difícil porque a tecnologia evolui muito mais depressa do que o direito. "
            "Uma coisa é certa: o debate está apenas começando."
        ),
    },
    "ru": {
        "A2": (
            "По субботам я часто хожу на рынок. "
            "Там я покупаю свежие фрукты и овощи на всю неделю. "
            "Продавцы очень приветливые и иногда дарят мне яблоко. "
            "После рынка я пью кофе в маленьком кафе на углу. "
            "Когда хорошая погода, я сижу на улице и смотрю на прохожих. "
            "Днём я готовлю что-нибудь вкусное для друзей."
        ),
        "B1": (
            "В больших городах многие люди каждый день ездят на работу на метро. "
            "Часто это удобнее, чем машина, потому что в дороге можно читать или слушать музыку. "
            "Правда, в час пик вагоны бывают переполнены, а на некоторых станциях приходится долго ждать. "
            "Поэтому многие пассажиры выходят из дома немного раньше. "
            "И всё же большинство довольно метро, особенно после того как открыли новые линии. "
            "Для окружающей среды общественный транспорт в любом случае лучший выбор."
        ),
        "B2": (
            "Всё больше компаний разрешают сотрудникам часть недели работать из дома. "
            "У этой перемены, которую ускорила пандемия, есть очевидные плюсы: меньше времени уходит на дорогу и больше свободы в планировании дня. "
            "Однако некоторым работникам не хватает ежедневного общения с коллегами, и им трудно отделять работу от личной жизни. "
            "Руководителям, в свою очередь, приходится учиться оценивать работу по результатам, а не по присутствию в офисе. "
            "Согласно ряду исследований, сегодня больше всего ценится смешанный формат. "
            "Остаётся вопрос, сохранится ли такая организация труда надолго."
        ),
        "C1": (
            "Искусственный интеллект проникает в сферы, которые прежде считались исключительно человеческими, от перевода до художественного творчества. "
            "Его сторонники видят в нём замечательный инструмент, способный избавить людей от рутинной работы и сделать знания доступнее. "
            "Критики же опасаются беспрецедентной концентрации власти в руках нескольких технологических гигантов, а также глубокой перестройки множества профессий. "
            "Между этими двумя взглядами законодатели пытаются выработать правила, которые поощряли бы инновации, не жертвуя защитой граждан. "
            "Задача тем сложнее, что технологии развиваются гораздо быстрее, чем право. "
            "Одно ясно наверняка: дискуссия только начинается."
        ),
    },
}

LEVELS = ("A2", "B1", "B2", "C1")
