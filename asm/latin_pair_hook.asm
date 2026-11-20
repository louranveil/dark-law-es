; Gancho de texto latino: la ficha "F9 a b" dibuja DOS letras de 8x16 en una celda de 16x16.
;
; Estado: prueba de concepto (spike), ver docs/re/latin-font-spike.md.
;
; El bucle de texto del juego (D1:4571) acepta un byte <C0 como glifo, FA-FD + byte como kanji, E5 y C3 como
; órdenes propias; el resto de C0-FF se entrega al despachador de comandos. Aquí se añade F9, que el juego no usa:
;
;     F9 a b    a y b son índices de letra en LatinFont (ver tools/build_latin_probe.py)
;
; Se engancha en D1:4587, donde el original compara con E5 (CMP #$E5 / BEQ $45F6, 4 bytes) y se sustituye por un
; JML a este código. Si el byte no es F9 se repite esa comparación y se vuelve a D1:458B, así que el resto del flujo
; no cambia. Si es F9, se copian las letras directamente al búfer de tiles de la ranura actual (mismas tablas
; D1:46AB/46DB/470B que usa la rutina original) y se salta a D1:465C, que escribe las 4 entradas del tilemap.
;
; Convenciones del motor que se respetan (verificadas en docs/re/text-engine.md y font.md):
;   - $0A45 es la ranura de glifo actual (0..23); con 24 o más no se dibuja y se salta a D1:468E.
;   - D1:468E hace PLY / INY: se apila Y apuntando al último byte de la ficha, así el siguiente byte es el nuevo.
;   - $0ADE cuenta caracteres mostrados; se incrementa una vez por ficha.
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

org $D14587
    JML LatinPairHook

org $D2BB80
LatinPairHook:
    CMP #$F9
    BEQ .pair
    CMP #$E5
    BNE .other
    JML $D145F6
.other:
    JML $D1458B

.pair:
    INC $0ADE
    REP #$20
    INY
    LDA [$1D],Y             ; byte bajo = letra izquierda, byte alto = letra derecha
    STA $20
    INY
    PHY                     ; Y queda en la letra derecha: PLY/INY de D1:468E pasa a la ficha siguiente
    SEP #$20
    LDA $0A45
    CMP #$18
    BCC .room
    JML $D1468E

.room:
    REP #$20
    AND #$00FF
    ASL A
    TAX
    LDA.l $D146DB,X         ; búfer de tiles de la ranura
    STA $0B
    LDA.l $D146AB,X         ; dirección del tilemap
    STA $0D
    LDA.l $D1470B,X         ; número de tile
    STA $0F

    LDA $20                 ; letra izquierda, mitad superior (tile 0) y mitad inferior (+$100)
    AND #$00FF
    JSR OffsetOfLetter
    LDY #$0000
    %CopyHalf()
    LDY #$0100
    %CopyHalf()

    LDA $21                 ; letra derecha, columna de tiles siguiente (+16 bytes)
    AND #$00FF
    JSR OffsetOfLetter
    LDY #$0010
    %CopyHalf()
    LDY #$0110
    %CopyHalf()

    JML $D1465C

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
