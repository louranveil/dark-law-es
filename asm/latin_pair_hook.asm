; Gancho de texto latino: la ficha "F9 a b" dibuja DOS letras de 8x16 en una celda de 16x16.
;
; Estado: prueba de concepto (spike), ver docs/re/latin-font-spike.md y docs/re/window-types.md.
;
; El juego tiene varios bucles de texto casi idénticos, uno por tipo de ventana (docs/re/window-types.md). Cada uno
; acepta un byte <C0 como glifo, FA-FD + byte como kanji, E5 y C3 como órdenes propias y entrega al despachador el
; resto de C0-FF. Aquí se añade F9, que el juego no usa:
;
;     F9 a b    a y b son índices de letra en LatinFont (ver tools/build_latin_probe.py)
;
; En cada bucle se sustituye la comparación con E5 (CMP #$E5 / BEQ, 4 bytes) por un JML a este código. Si el byte no es
; F9 se repite esa comparación y se vuelve a la instrucción siguiente, así que el resto del flujo no cambia. Si es F9,
; se copian las letras directamente al búfer de tiles de la ranura actual (las tablas de ranuras de cada bucle) y se
; salta a la parte del bucle que escribe las entradas del tilemap.
;
; Convenciones del motor que se respetan (verificadas en docs/re/text-engine.md y font.md):
;   - El contador de ranura de cada bucle ($0A45 o $0A47) indica la ranura actual; con el límite alcanzado no se dibuja.
;   - La rutina de salida hace PLY / INY: se apila Y apuntando al último byte de la ficha, así el siguiente byte es el nuevo.
;   - $0ADE cuenta caracteres mostrados; se incrementa una vez por ficha (efecto no verificado).
;   - $0B/$0D/$0F son temporales que la rutina original reasigna en cada glifo; $20 se usa aquí como temporal.

hirom

; Copia 16 bytes (un tile) desde LatinFont,X hasta ($0B),Y y deja X e Y avanzados 16.
macro CopyHalf()
    LDA.l LatinFont,X : STA ($0B),Y : INX : INX : INY : INY
    LDA.l LatinFont,X : STA ($0B),Y : INX : INX : INY : INY
    LDA.l LatinFont,X : STA ($0B),Y : INX : INX : INY : INY
    LDA.l LatinFont,X : STA ($0B),Y : INX : INX : INY : INY
    LDA.l LatinFont,X : STA ($0B),Y : INX : INX : INY : INY
    LDA.l LatinFont,X : STA ($0B),Y : INX : INX : INY : INY
    LDA.l LatinFont,X : STA ($0B),Y : INX : INX : INY : INY
    LDA.l LatinFont,X : STA ($0B),Y : INX : INX : INY : INY
endmacro

; Cuerpo del gancho de un bucle. Parámetros:
;   e5target  destino del BEQ original de la comparación con E5
;   next      instrucción que sigue a los 4 bytes sustituidos
;   counter   contador de ranura del bucle
;   limit     número de ranuras; con counter >= limit no se dibuja
;   skip      dónde continuar cuando no hay ranura (el PLY/INY del bucle)
;   buftab    tabla de búferes de tiles por ranura
;   maptab    tabla de direcciones de tilemap por ranura
;   numtab    tabla de números de tile por ranura
;   tail      parte del bucle que escribe el tilemap, avanza el contador y sigue
macro LatinHook(e5target, next, counter, limit, skip, buftab, maptab, numtab, tail)
    CMP #$F9
    BEQ ?pair
    CMP #$E5
    BNE ?other
    JML <e5target>
?other:
    JML <next>

?pair:
    INC $0ADE
    REP #$20
    INY
    LDA [$1D],Y             ; byte bajo = letra izquierda, byte alto = letra derecha
    STA $20
    INY
    PHY                     ; Y queda en la letra derecha: PLY/INY del bucle pasa a la ficha siguiente
    SEP #$20
    LDA <counter>
    CMP #<limit>
    BCC ?room
    JML <skip>

?room:
    REP #$20
    AND #$00FF
    ASL A
    TAX
    LDA.l <buftab>,X        ; búfer de tiles de la ranura
    STA $0B
    LDA.l <maptab>,X        ; dirección del tilemap
    STA $0D
    LDA.l <numtab>,X        ; número de tile
    STA $0F

    LDA $20                 ; letra izquierda: mitad superior (tile 0) y mitad inferior (+$100)
    AND #$00FF
    JSR OffsetOfLetter
    LDY #$0000
    %CopyHalf()
    LDY #$0100
    %CopyHalf()

    LDA $21                 ; letra derecha: columna de tiles siguiente (+16 bytes)
    AND #$00FF
    JSR OffsetOfLetter
    LDY #$0010
    %CopyHalf()
    LDY #$0110
    %CopyHalf()

    JML <tail>
endmacro

; Bucle 1 (ventana de tipo 1, 24 ranuras): D1:4587 era CMP #$E5 / BEQ $45F6
org $D14587
    JML Loop1Hook

; Bucle 2 (ventana de tipo 2, 32 ranuras): D1:477D era CMP #$E5 / BEQ $47E0
org $D1477D
    JML Loop2Hook

org $D2BB80
Loop1Hook:
    %LatinHook($D145F6, $D1458B, $0A45, $18, $D1468E, $D146DB, $D146AB, $D1470B, $D1465C)

Loop2Hook:
    %LatinHook($D147E0, $D14781, $0A47, $20, $D1486E, $D148B3, $D14873, $D148F3, $D14851)

; Entrada A = índice de letra; salida X = índice * 32 (cada letra son 32 bytes: tile superior y tile inferior).
OffsetOfLetter:
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    TAX
    RTS

; Fuente latina de 8x16 en 2 bpp: 32 bytes por letra (16 del tile superior y 16 del inferior).
org $D2C000
LatinFont:
    incbin "latin-font.bin"
