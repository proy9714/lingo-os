"""Dictation sentences written for Lingo OS, graded A1 → C1 (for Japanese roughly N5 → N1)."""

LEVELS = ("A1", "A2", "B1", "B2", "C1")

SENTENCES: dict[str, dict[str, list[str]]] = {
    "de": {
        "A1": [
            "Ich trinke jeden Morgen einen Kaffee.",
            "Mein Bruder wohnt in Hamburg.",
            "Wir gehen heute Abend ins Kino.",
            "Das Wetter ist heute sehr schön.",
            "Wo ist der nächste Bahnhof?",
        ],
        "A2": [
            "Gestern habe ich mit meiner Schwester telefoniert.",
            "Kannst du mir bitte das Salz geben?",
            "Am Wochenende fahren wir zu meinen Großeltern.",
            "Der Zug hatte leider zwanzig Minuten Verspätung.",
            "Ich suche eine Wohnung in der Nähe vom Zentrum.",
        ],
        "B1": [
            "Wenn ich mehr Zeit hätte, würde ich öfter Sport machen.",
            "Er hat sich entschieden, nächstes Jahr im Ausland zu studieren.",
            "Obwohl es geregnet hat, sind wir spazieren gegangen.",
            "Die Wohnung ist zwar klein, aber dafür sehr günstig.",
            "Ich habe vergessen, meinen Termin beim Arzt abzusagen.",
        ],
        "B2": [
            "Die Regierung plant, die Steuern für kleine Unternehmen deutlich zu senken.",
            "Hätte ich das früher gewusst, wäre ich gar nicht erst hingefahren.",
            "Viele Menschen unterschätzen, wie viel Energie im Haushalt verschwendet wird.",
            "Trotz der hohen Kosten halten die meisten Experten das Projekt für sinnvoll.",
            "Es wird erwartet, dass die Mieten in den Großstädten weiter steigen.",
        ],
        "C1": [
            "Angesichts der angespannten Lage sahen sich die Verantwortlichen gezwungen, die Veranstaltung abzusagen.",
            "Die Studie legt nahe, dass soziale Kontakte maßgeblich zur Lebenserwartung beitragen.",
            "Ungeachtet aller Bedenken wurde das Gesetz mit knapper Mehrheit verabschiedet.",
            "Wer sich eingehend mit dem Thema befasst, stößt schnell auf widersprüchliche Angaben.",
            "Die Debatte über die Zukunft der Arbeit wird zunehmend von ideologischen Positionen geprägt.",
        ],
    },
    "es": {
        "A1": [
            "Me llamo Ana y vivo en Madrid.",
            "Mi hermano tiene dos perros.",
            "Hoy hace mucho calor.",
            "¿Dónde está la estación de tren?",
            "Todos los días bebo un café con leche.",
        ],
        "A2": [
            "Ayer fui al mercado con mi madre.",
            "¿Me puedes pasar la sal, por favor?",
            "El fin de semana vamos a visitar a mis abuelos.",
            "El autobús llegó con veinte minutos de retraso.",
            "Estoy buscando un piso cerca del centro.",
        ],
        "B1": [
            "Si tuviera más tiempo, haría deporte con más frecuencia.",
            "Ha decidido estudiar en el extranjero el año que viene.",
            "Aunque llovía, salimos a dar un paseo.",
            "El piso es pequeño, pero a cambio es muy barato.",
            "Se me olvidó cancelar la cita con el médico.",
        ],
        "B2": [
            "El gobierno pretende reducir los impuestos a las pequeñas empresas.",
            "Si lo hubiera sabido antes, no habría ido.",
            "Mucha gente subestima cuánta energía se desperdicia en casa.",
            "A pesar del elevado coste, la mayoría de los expertos considera razonable el proyecto.",
            "Se espera que los alquileres sigan subiendo en las grandes ciudades.",
        ],
        "C1": [
            "Ante la tensa situación, los responsables se vieron obligados a cancelar el evento.",
            "El estudio sugiere que las relaciones sociales contribuyen de manera decisiva a la esperanza de vida.",
            "Pese a todas las reservas, la ley fue aprobada por una estrecha mayoría.",
            "Quien profundiza en el tema enseguida se topa con datos contradictorios.",
            "El debate sobre el futuro del trabajo está cada vez más marcado por posturas ideológicas.",
        ],
    },
    "ja": {
        "A1": [
            "毎朝コーヒーを飲みます。",
            "私の兄は東京に住んでいます。",
            "今日はとても暑いです。",
            "駅はどこですか。",
            "週末に友達と映画を見ました。",
        ],
        "A2": [
            "昨日、母と一緒に買い物に行きました。",
            "すみません、塩を取ってもらえますか。",
            "電車が二十分遅れて到着しました。",
            "駅の近くで新しいアパートを探しています。",
            "雨が降っていたので、家で本を読みました。",
        ],
        "B1": [
            "もっと時間があれば、毎日運動するのに。",
            "彼は来年、海外の大学で勉強することにしました。",
            "部屋は狭いけれど、そのかわり家賃がとても安いです。",
            "病院の予約をキャンセルするのを忘れてしまいました。",
            "雨が降っていたにもかかわらず、散歩に出かけました。",
        ],
        "B2": [
            "政府は中小企業の税金を大幅に引き下げる方針を示した。",
            "もっと早く知っていたら、わざわざ行かなかったのに。",
            "家庭で無駄になっているエネルギーの量を、多くの人が過小評価している。",
            "費用は高いものの、専門家の大半はこの計画を有意義だと考えている。",
            "大都市では家賃がさらに上がると予想されている。",
        ],
        "C1": [
            "緊迫した情勢を受け、主催者はイベントの中止を余儀なくされた。",
            "その研究は、人とのつながりが寿命に大きく影響することを示唆している。",
            "あらゆる懸念をよそに、法案は僅差で可決された。",
            "このテーマを掘り下げると、矛盾する情報にすぐ突き当たる。",
            "働き方の将来をめぐる議論は、ますますイデオロギー色を帯びている。",
        ],
    },
}
