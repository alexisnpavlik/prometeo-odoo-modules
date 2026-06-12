/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from '@odoo/owl';
import { Dialog } from '@web/core/dialog/dialog';
import { usePos } from '@point_of_sale/app/store/pos_hook';
import { _t } from "@web/core/l10n/translation";

export class PasswordValidationPopup extends Component {
    static components = { Dialog };
    static template = "pos_special_approval_omax.PasswordValidationPopup";
    static props = ["close", "getPayload", "title"];

    setup() {
        this.pos = usePos();
        this.state = useState({
            password: "",
            showVirtualKeyboard: false,
            showPassword: false,
            capsLock: false,
            shift: false,
            currentLayout: 'main' // 'main', 'symbols', 'numbers'
        });
        this.inputRef = useRef("passwordInput");

        this._boundHandleKeyDown = this.handleKeyDown.bind(this);
        
        onMounted(() => {
            document.addEventListener('keydown', this._boundHandleKeyDown);
            if (this.inputRef.el) {
                this.inputRef.el.focus();
            }
            // Check if virtual keyboard should be shown
            if (this.pos.config.virtual_keyboard) {
                this.state.showVirtualKeyboard = true;
            }
        });
        
        onWillUnmount(() => {
            document.removeEventListener('keydown', this._boundHandleKeyDown);
        });
    }
    
    handleKeyDown(event) {
        if (event.key === 'Escape' && !this.isResolved) {
            event.preventDefault();
            event.stopPropagation();
            this.cancel();
        } else if (event.key === 'Enter' && this.state.password.trim()) {
            event.preventDefault();
            this.confirm();
        }
    }

    onPasswordInput(ev) {
        this.state.password = ev.target.value;
    }

    onVirtualKeyPress(key, isSpecial = false) {
        if (key === 'backspace') {
            this.state.password = this.state.password.slice(0, -1);
        } else if (key === 'clear') {
            this.state.password = '';
        } else if (key === 'enter') {
            this.confirm();
        } else if (key === 'space') {
            this.state.password += ' ';
        } else if (key === 'tab') {
            this.state.password += '\t';
        } else if (key === 'shift') {
            this.state.shift = !this.state.shift;
        } else if (key === 'caps') {
            this.state.capsLock = !this.state.capsLock;
        } else if (key === 'symbols') {
            this.state.currentLayout = this.state.currentLayout === 'symbols' ? 'main' : 'symbols';
        } else if (key === 'numbers') {
            this.state.currentLayout = this.state.currentLayout === 'numbers' ? 'main' : 'numbers';
        } else if (key === 'main') {
            this.state.currentLayout = this.state.currentLayout === 'main';
        } else if (!isSpecial) {
            let keyToAdd = key;
            
            // Apply case transformation
            if (this.isAlpha(key)) {
                if (this.state.capsLock || this.state.shift) {
                    keyToAdd = key.toUpperCase();
                } else {
                    keyToAdd = key.toLowerCase();
                }
            }
            
            // Apply shift for symbols
            if (this.state.shift && this.symbolShiftMap[key]) {
                keyToAdd = this.symbolShiftMap[key];
            }
            
            this.state.password += keyToAdd;
            
            // Reset shift after use (but not caps lock)
            if (this.state.shift) {
                this.state.shift = false;
            }
        }
        
        // Update the actual input field
        if (this.inputRef.el) {
            this.inputRef.el.value = this.state.password;
        }
    }

    isAlpha(char) {
        return /^[a-zA-Z]$/.test(char);
    }

    get symbolShiftMap() {
        return {
            '1': '!', '2': '@', '3': '#', '4': '$', '5': '%',
            '6': '^', '7': '&', '8': '*', '9': '(', '0': ')',
            '-': '_', '=': '+', '[': '{', ']': '}', '\\': '|',
            ';': ':', "'": '"', ',': '<', '.': '>', '/': '?',
            '`': '~'
        };
    }

    get virtualKeyboardKeys() {
        if (this.state.currentLayout === 'numbers') {
            return {
                rows: [
                    [
                        { key: '1', display: '1' },
                        { key: '2', display: '2' },
                        { key: '3', display: '3' },
                        { key: '4', display: '4' },
                        { key: '5', display: '5' }
                    ],
                    [
                        { key: '6', display: '6' },
                        { key: '7', display: '7' },
                        { key: '8', display: '8' },
                        { key: '9', display: '9' },
                        { key: '0', display: '0' }
                    ],
                    [
                        { key: '.', display: '.' },
                        { key: ',', display: ',' },
                        { key: '+', display: '+' },
                        { key: '-', display: '-' },
                        { key: '=', display: '=' }
                    ]
                ],
                bottomRow: [
                    { key: 'main', display: 'ABC', class: 'btn-secondary layout-key text-white' },
                    { key: 'symbols', display: '#+=', class: 'btn-secondary layout-key text-white' },
                    { key: 'space', display: 'Space', class: 'btn-light space-key' },
                    { key: 'backspace', display: '⌫', class: 'btn-warning' }
                ]
            };
        } else if (this.state.currentLayout === 'symbols') {
            return {
                rows: [
                    [
                        { key: '!', display: '!' },
                        { key: '@', display: '@' },
                        { key: '#', display: '#' },
                        { key: '$', display: '$' },
                        { key: '%', display: '%' },
                        { key: '^', display: '^' },
                        { key: '&', display: '&' },
                        { key: '*', display: '*' }
                    ],
                    [
                        { key: '(', display: '(' },
                        { key: ')', display: ')' },
                        { key: '-', display: '-' },
                        { key: '_', display: '_' },
                        { key: '=', display: '=' },
                        { key: '+', display: '+' },
                        { key: '[', display: '[' },
                        { key: ']', display: ']' }
                    ],
                    [
                        { key: '{', display: '{' },
                        { key: '}', display: '}' },
                        { key: '\\', display: '\\' },
                        { key: '|', display: '|' },
                        { key: ';', display: ';' },
                        { key: ':', display: ':' },
                        { key: '"', display: '"' },
                        { key: "'", display: "'" }
                    ],
                    [
                        { key: '<', display: '<' },
                        { key: '>', display: '>' },
                        { key: ',', display: ',' },
                        { key: '.', display: '.' },
                        { key: '/', display: '/' },
                        { key: '?', display: '?' },
                        { key: '`', display: '`' },
                        { key: '~', display: '~' }
                    ]
                ],
                bottomRow: [
                    { key: 'main', display: 'ABC', class: 'btn-secondary layout-key text-white' },
                    { key: 'numbers', display: '123', class: 'btn-secondary layout-key text-white' },
                    { key: 'space', display: 'Space', class: 'btn-light space-key' },
                    { key: 'backspace', display: '⌫', class: 'btn-warning' }
                ]
            };
        } else {
            // Main QWERTY layout
            const isUpperCase = this.state.capsLock || this.state.shift;
            return {
                rows: [
                    [
                        { key: '1', display: this.state.shift ? '!' : '1' },
                        { key: '2', display: this.state.shift ? '@' : '2' },
                        { key: '3', display: this.state.shift ? '#' : '3' },
                        { key: '4', display: this.state.shift ? '$' : '4' },
                        { key: '5', display: this.state.shift ? '%' : '5' },
                        { key: '6', display: this.state.shift ? '^' : '6' },
                        { key: '7', display: this.state.shift ? '&' : '7' },
                        { key: '8', display: this.state.shift ? '*' : '8' },
                        { key: '9', display: this.state.shift ? '(' : '9' },
                        { key: '0', display: this.state.shift ? ')' : '0' }
                    ],
                    [
                        { key: 'q', display: isUpperCase ? 'Q' : 'q' },
                        { key: 'w', display: isUpperCase ? 'W' : 'w' },
                        { key: 'e', display: isUpperCase ? 'E' : 'e' },
                        { key: 'r', display: isUpperCase ? 'R' : 'r' },
                        { key: 't', display: isUpperCase ? 'T' : 't' },
                        { key: 'y', display: isUpperCase ? 'Y' : 'y' },
                        { key: 'u', display: isUpperCase ? 'U' : 'u' },
                        { key: 'i', display: isUpperCase ? 'I' : 'i' },
                        { key: 'o', display: isUpperCase ? 'O' : 'o' },
                        { key: 'p', display: isUpperCase ? 'P' : 'p' }
                    ],
                    [
                        { key: 'a', display: isUpperCase ? 'A' : 'a' },
                        { key: 's', display: isUpperCase ? 'S' : 's' },
                        { key: 'd', display: isUpperCase ? 'D' : 'd' },
                        { key: 'f', display: isUpperCase ? 'F' : 'f' },
                        { key: 'g', display: isUpperCase ? 'G' : 'g' },
                        { key: 'h', display: isUpperCase ? 'H' : 'h' },
                        { key: 'j', display: isUpperCase ? 'J' : 'j' },
                        { key: 'k', display: isUpperCase ? 'K' : 'k' },
                        { key: 'l', display: isUpperCase ? 'L' : 'l' }
                    ],
                    [
                        { key: 'shift', display: '⇧', class: `btn-info shift-key ${this.state.shift ? 'active' : ''}`, special: true },
                        { key: 'z', display: isUpperCase ? 'Z' : 'z' },
                        { key: 'x', display: isUpperCase ? 'X' : 'x' },
                        { key: 'c', display: isUpperCase ? 'C' : 'c' },
                        { key: 'v', display: isUpperCase ? 'V' : 'v' },
                        { key: 'b', display: isUpperCase ? 'B' : 'b' },
                        { key: 'n', display: isUpperCase ? 'N' : 'n' },
                        { key: 'm', display: isUpperCase ? 'M' : 'm' },
                        { key: 'backspace', display: '⌫', class: 'btn-warning backspace-key', special: true }
                    ]
                ],
                bottomRow: [
                    { key: 'numbers', display: '123', class: 'btn-secondary layout-key text-white' },
                    { key: 'symbols', display: '#+=', class: 'btn-secondary layout-key text-white' },
                    { key: 'caps', display: 'Caps', class: `btn-info caps-key ${this.state.capsLock ? 'active' : ''}`, special: true },
                    { key: 'space', display: 'Space', class: 'btn-light space-key' },
                    { key: 'clear', display: 'Clear', class: 'btn-outline-danger clear-key' },
                    { key: 'enter', display: 'Enter', class: 'btn-success enter-key' }
                ]
            };
        }
    }

    togglePasswordVisibility() {
        this.state.showPassword = !this.state.showPassword;
    }

    async confirm() {
        if (!this.state.password.trim()) {
            return;
        }

        this.props.getPayload({
            password: this.state.password.trim()
        });
        this.props.close();
    }

    cancel() {
        this.props.getPayload(null);
        this.props.close();
    }
}