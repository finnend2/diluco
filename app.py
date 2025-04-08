from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, flash
import mysql.connector
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from datetime import datetime
import stripe
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set Stripe API keys from environment variables
stripe.api_key = os.getenv('STRIPE_SECRET_KEY', 'sk_test_51R8YJjR1pVzMxLp1xW12cSL2So6x9pAawOgoH8qq4bpbnWDiggLmw8f8kSaZV53FTp4t86NJKEo7TzWYXOsoRO6p004FXHpsJI')
STRIPE_PUBLIC_KEY = os.getenv('STRIPE_PUBLIC_KEY', 'pk_test_51R8YJjR1pVzMxLp1U1puxsgzIGr9MT5Vp7UKZd9Ym2uI95R8z9OcH2YWaLgJpDVozn3tgq9gXoHx4R9Djf0r9MVb00H7simJtR')

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dsagasdigasdgsda-212121-uduqg7dgd-7738372823-disudfg')  

# MySQL connection configuration
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'diluco'
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

@app.route('/')
def index():
    if 'cart' not in session:
        session['cart'] = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT ID, NOMBRE, PRECIO, IMAGEN FROM PRODUCTO")
        productos = cursor.fetchall()
        
    except mysql.connector.Error as err:
        print("Database error:", err)
        productos = []
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    
    return render_template('index.html', cart=session['cart'], productos=productos)

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    try:
        product_id = int(request.form['product_id'])
        product_name = request.form['product_name']
        product_price = float(request.form['product_price'])
        product_image = request.form.get('product_image', '')  # Optional image
        quantity = int(request.form.get('quantity', 1))
        
        cart = session.get('cart', [])
        # Increase quantity if product already in cart, else add it
        for item in cart:
            if item['id'] == product_id:
                item['quantity'] += quantity
                break
        else:
            cart.append({
                'id': product_id,
                'name': product_name,
                'price': product_price,
                'image': product_image,
                'quantity': quantity
            })
        
        session['cart'] = cart
        
        # Return JSON if AJAX request, else redirect
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'cart_count': len(cart)})
        else:
            return redirect(url_for('checkout'))
            
    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': str(e)}), 400
        else:
            flash(f"Error al agregar al carrito: {str(e)}", "error")
            return redirect(url_for('index'))

@app.route('/remove_item', methods=['POST'])
def remove_item():
    try:
        data = request.get_json()
        item_index = int(data['itemId'])
        cart = session.get('cart', [])
        
        if 0 <= item_index < len(cart):
            cart.pop(item_index)
            session['cart'] = cart
            return jsonify({
                'success': True,
                'cart_count': len(cart),
                'total': sum(item['price'] * item['quantity'] for item in cart)
            })
        return jsonify({'success': False}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/checkout')
def checkout():
    cart = session.get('cart', [])
    if not cart:
        flash("Tu carrito está vacío", "warning")
        return redirect(url_for('index'))
    
    total = sum(item['price'] * item['quantity'] for item in cart)
    return render_template('checkout.html', cart=cart, total=total)

@app.route('/process_checkout', methods=['POST'])
def process_checkout():
    # Validate required fields in form
    required_fields = ['run', 'nombre', 'apellido', 'email', 'direccion', 'telefono']
    if not all(field in request.form for field in required_fields):
        flash("Por favor completa todos los campos requeridos", "error")
        return redirect(url_for('checkout'))

    cart = session.get('cart', [])
    if not cart:
        flash("Tu carrito está vacío", "error")
        return redirect(url_for('index'))

    orden_id = None
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verify all products in the cart still exist
        product_ids = [item['id'] for item in cart]
        placeholders = ','.join(['%s'] * len(product_ids))
        cursor.execute(f"SELECT ID FROM PRODUCTO WHERE ID IN ({placeholders})", product_ids)
        existing_products = {row[0] for row in cursor.fetchall()}
        for item in cart:
            if item['id'] not in existing_products:
                flash(f"El producto {item['name']} ya no está disponible", "error")
                return redirect(url_for('checkout'))

        # Process client data
        run = request.form['run']
        cursor.execute("SELECT RUN FROM CLIENTE WHERE RUN = %s", (run,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO CLIENTE (RUN, NOMBRE, APELLIDO, EMAIL, DIRECCION, TELEFONO) VALUES (%s, %s, %s, %s, %s, %s)",
                (run, request.form['nombre'], request.form['apellido'], 
                 request.form['email'], request.form['direccion'], request.form['telefono'])
            )

        # Create order record
        total = sum(item['price'] * item['quantity'] for item in cart)
        cursor.execute(
            "INSERT INTO ORDEN (TOTAL, CLIENTE_RUN, FECHA) VALUES (%s, %s, NOW())",
            (total, run)
        )
        orden_id = cursor.lastrowid
        
        # Insert order items
        for item in cart:
            cursor.execute(
                "INSERT INTO ORDEN_ITEM (ORDEN_ID, PRODUCTO_ID, CANTIDAD, PRECIO_UNITARIO) VALUES (%s, %s, %s, %s)",
                (orden_id, item['id'], item['quantity'], item['price'])
            )
        
        conn.commit()
        session.pop('cart', None)
        # Redirect to the payment page (/pagos) and pass the order ID as a query parameter
        return redirect(url_for('payment_page', orden_id=orden_id))
    
    except mysql.connector.Error as err:
        if conn:
            conn.rollback()
        print("Database error:", err)
        flash("Error al procesar tu pedido. Por favor intenta nuevamente.", "error")
        return redirect(url_for('checkout'))
    
    except Exception as e:
        if conn:
            conn.rollback()
        print("Unexpected error:", e)
        flash("Ocurrió un error inesperado. Por favor intenta nuevamente.", "error")
        return redirect(url_for('checkout'))
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# Modified payment page route to receive the order ID (orden_id)
@app.route('/pagos')
def payment_page():
    orden_id = request.args.get('orden_id')
    return render_template('pagos.html', stripe_public_key=STRIPE_PUBLIC_KEY, orden_id=orden_id)

# Modified payment processing to include the order ID from a hidden form field
@app.route('/procesar_pago', methods=['POST'])
def procesar_pago():
    try:
        card_name = request.form['card_name']
        email = request.form['email']
        # Retrieve order ID sent as a hidden field from pagos.html
        orden_id = request.form.get('orden_id')
        amount = 60000  # 60,000 COP in the smallest currency unit
        
        # Create PaymentIntent with Stripe
        intent = stripe.PaymentIntent.create(
            amount=amount,
            currency='cop',  # Colombian Pesos
            description=f"Sesión psicológica para {email}",
            receipt_email=email,
            metadata={
                'customer_name': card_name,
                'service': 'Sesión Psicológica',
                'orden_id': orden_id
            }
        )
        
        # Redirect to confirmation page including the order ID in the query string
        return redirect(url_for('confirmacion_pago', client_secret=intent.client_secret, orden_id=orden_id))
    
    except Exception as e:
        return render_template('error.html', error=str(e))

# Updated confirmation route to receive the order ID
@app.route('/confirmacion')
def confirmacion_pago():
    client_secret = request.args.get('client_secret')
    orden_id = request.args.get('orden_id')
    # You can either automatically trigger invoice generation here
    # or show a page that includes order details and a link/button to download the invoice.
    return render_template('confirmacion.html', client_secret=client_secret, orden_id=orden_id)

@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = os.getenv('STRIPE_WEBHOOK_SECRET')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except stripe.error.SignatureVerificationError as e:
        return jsonify({'error': str(e)}), 400

    # Handle important events
    if event['type'] == 'payment_intent.succeeded':
        payment_intent = event['data']['object']
        print(f"Pago exitoso: {payment_intent['id']}")
    elif event['type'] == 'payment_intent.payment_failed':
        payment_intent = event['data']['object']
        print(f"Pago fallido: {payment_intent.get('last_payment_error', {}).get('message', 'Error desconocido')}")

    return jsonify({'success': True}), 200

@app.route('/thank_you/<int:orden_id>')
def thank_you(orden_id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Retrieve order details
        cursor.execute("""
            SELECT o.*, c.NOMBRE, c.APELLIDO 
            FROM ORDEN o
            JOIN CLIENTE c ON o.CLIENTE_RUN = c.RUN
            WHERE o.ID = %s
        """, (orden_id,))
        orden = cursor.fetchone()
        
        if not orden:
            flash("Orden no encontrada", "error")
            return redirect(url_for('index'))
        
        # Retrieve order items
        cursor.execute("""
            SELECT oi.*, p.NOMBRE as producto_nombre
            FROM ORDEN_ITEM oi
            JOIN PRODUCTO p ON oi.PRODUCTO_ID = p.ID
            WHERE oi.ORDEN_ID = %s
        """, (orden_id,))
        items = cursor.fetchall()
        
        return render_template('thank_you.html', 
                               orden=orden,
                               items=items,
                               orden_id=orden_id)
    except mysql.connector.Error as err:
        print("Database error:", err)
        flash("Error al recuperar los detalles de tu orden", "error")
        return redirect(url_for('index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/download_invoice/<int:orden_id>')
def download_invoice(orden_id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Retrieve order details
        cursor.execute("""
            SELECT o.*, c.NOMBRE, c.APELLIDO, c.DIRECCION
            FROM ORDEN o
            JOIN CLIENTE c ON o.CLIENTE_RUN = c.RUN
            WHERE o.ID = %s
        """, (orden_id,))
        orden = cursor.fetchone()
        
        if not orden:
            return "Orden no encontrada", 404
        
        # Retrieve order items
        cursor.execute("""
            SELECT oi.*, p.NOMBRE as producto_nombre
            FROM ORDEN_ITEM oi
            JOIN PRODUCTO p ON oi.PRODUCTO_ID = p.ID
            WHERE oi.ORDEN_ID = %s
        """, (orden_id,))
        items = cursor.fetchall()
        
        # Create PDF invoice using ReportLab
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        
        # Header
        p.setFont("Helvetica-Bold", 16)
        p.drawString(50, height - 50, "Factura")
        p.setFont("Helvetica", 12)
        p.drawString(50, height - 80, f"Orden #: {orden_id}")
        p.drawString(50, height - 100, f"Fecha: {orden['FECHA'].strftime('%d/%m/%Y')}")
        
        # Client information
        p.drawString(50, height - 130, "Cliente:")
        p.drawString(50, height - 150, f"{orden['NOMBRE']} {orden['APELLIDO']}")
        p.drawString(50, height - 170, f"Dirección: {orden['DIRECCION']}")
        
        # Order items header
        p.drawString(50, height - 200, "Detalles del Pedido:")
        p.drawString(50, height - 220, "Producto")
        p.drawString(250, height - 220, "Cantidad")
        p.drawString(350, height - 220, "Precio Unit.")
        p.drawString(450, height - 220, "Subtotal")
        
        y = height - 240
        for item in items:
            p.drawString(50, y, item['producto_nombre'])
            p.drawString(250, y, str(item['CANTIDAD']))
            p.drawString(350, y, f"${item['PRECIO_UNITARIO']:.2f}")
            p.drawString(450, y, f"${item['PRECIO_UNITARIO'] * item['CANTIDAD']:.2f}")
            y -= 20
        
        # Total amount
        p.drawString(350, y - 30, "Total:")
        p.drawString(450, y - 30, f"${orden['TOTAL']:.2f}")
        
        p.showPage()
        p.save()
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"factura_{orden_id}.pdf",
            mimetype='application/pdf'
        )
    except Exception as e:
        print("Error generating invoice:", e)
        return "Error al generar la factura", 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

if __name__ == '__main__':
    app.run(debug=True)
